"""FastAPI composition root; room rules and Redis are separate packages."""

import asyncio
from contextlib import asynccontextmanager
import hmac
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import parse_bool, validate_production_settings
from app.observability import OperationalMetrics
from app.api.rooms import router as room_router
from app.api.editor import router as editor_router
from app.api.feedback import router as feedback_router
from app.api.websocket import router as websocket_router
from app.realtime.connection_manager import RoomConnectionManager
from app.realtime.coordinator import RoomCoordinator
from app.realtime.deadline_scheduler import DeadlineScheduler
from app.realtime.match_setup import MatchSetupPolicy
from app.realtime.recovery_worker import RecoveryWorker
from app.rooms.redis_repository import RedisRoomRepository
from app.rooms.service import RoomPolicy, RoomService
from app.runner.redis_repository import RedisRunnerRepository
from app.runner.result_processor import RunnerResultProcessor
from app.runner.result_worker import RunnerResultWorker
from app.runner.service import RunnerService


def _allowed_origins() -> tuple[str, ...]:
    value = os.getenv(
        "CODEMAFIA_ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    )
    origins = tuple(item.strip() for item in value.split(",") if item.strip())
    if not origins or "*" in origins:
        raise ValueError("Explicit browser origins are required for credentialed rooms.")
    return origins


allowed_origins = _allowed_origins()
environment = os.getenv("CODEMAFIA_ENV", "development").lower()
secure_guest_cookie = parse_bool(
    os.getenv("CODEMAFIA_SECURE_COOKIE", "true" if environment != "development" else "false"),
    name="CODEMAFIA_SECURE_COOKIE",
)
accept_new_matches = parse_bool(
    os.getenv("CODEMAFIA_ACCEPT_NEW_MATCHES", "true"),
    name="CODEMAFIA_ACCEPT_NEW_MATCHES",
)
allow_draft_content = parse_bool(
    os.getenv("CODEMAFIA_ALLOW_DRAFT_CONTENT", "true" if environment == "development" else "false"),
    name="CODEMAFIA_ALLOW_DRAFT_CONTENT",
)
guest_cookie_samesite = os.getenv("CODEMAFIA_COOKIE_SAMESITE", "lax").lower()
if guest_cookie_samesite not in {"lax", "strict", "none"}:
    raise ValueError("Guest-cookie SameSite must be lax, strict, or none.")
if guest_cookie_samesite == "none" and not secure_guest_cookie:
    raise ValueError("Cross-site guest cookies require Secure mode and HTTPS.")
editor_websocket_url = os.getenv(
    "CODEMAFIA_EDITOR_WS_URL", "ws://127.0.0.1:1234/api/rooms/editor/ws",
)
editor_service_key = os.getenv("CODEMAFIA_EDITOR_SERVICE_KEY", "")
signing_key = os.getenv("CODEMAFIA_RUNNER_RESULT_HMAC_KEY", "")
metrics_token = os.getenv("CODEMAFIA_METRICS_TOKEN", "")
if signing_key and len(signing_key.encode("utf-8")) < 32:
    raise ValueError("CODEMAFIA_RUNNER_RESULT_HMAC_KEY must contain at least 32 bytes.")
validate_production_settings(
    environment=environment,
    allowed_origins=allowed_origins,
    secure_cookie=secure_guest_cookie,
    editor_websocket_url=editor_websocket_url,
    editor_service_key=editor_service_key,
    runner_result_key=signing_key,
    redis_url=os.getenv("REDIS_URL"),
    metrics_token=metrics_token,
    allow_draft_content=allow_draft_content,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = Redis.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        decode_responses=False,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    app.state.redis_client = client
    app.state.allowed_origins = allowed_origins
    app.state.secure_guest_cookie = secure_guest_cookie
    app.state.guest_cookie_samesite = guest_cookie_samesite
    app.state.accept_new_matches = accept_new_matches
    app.state.allow_draft_content = allow_draft_content
    app.state.operational_metrics = OperationalMetrics()
    app.state.editor_service_key = editor_service_key
    app.state.editor_websocket_url = editor_websocket_url
    repository = RedisRoomRepository(client)
    runner_repository = RedisRunnerRepository(client)
    app.state.room_repository = repository
    app.state.room_service = RoomService(
        repository,
        policy=RoomPolicy(
            room_ttl_seconds=int(os.getenv("CODEMAFIA_ROOM_TTL_SECONDS", "3600")),
            credential_ttl_seconds=int(os.getenv("CODEMAFIA_CREDENTIAL_TTL_SECONDS", "3600")),
            join_window_seconds=int(os.getenv("CODEMAFIA_JOIN_WINDOW_SECONDS", "60")),
            max_join_attempts=int(os.getenv("CODEMAFIA_MAX_JOIN_ATTEMPTS", "30")),
        ),
    )
    app.state.room_connection_manager = RoomConnectionManager(app.state.room_service.authenticate_player)
    app.state.runner_repository = runner_repository
    app.state.runner_service = RunnerService(
        repository, runner_repository, enabled=bool(signing_key),
    )
    app.state.room_coordinator = RoomCoordinator(
        repository, app.state.room_connection_manager,
        setup_policy=MatchSetupPolicy(
            category_vote_seconds=int(os.getenv("CODEMAFIA_CATEGORY_VOTE_SECONDS", "30")),
            role_reveal_seconds=int(os.getenv("CODEMAFIA_ROLE_REVEAL_SECONDS", "8")),
            coding_round_seconds=int(os.getenv("CODEMAFIA_CODING_ROUND_SECONDS", "180")),
            meeting_discussion_seconds=int(os.getenv("CODEMAFIA_MEETING_DISCUSSION_SECONDS", "30")),
            player_vote_seconds=int(os.getenv("CODEMAFIA_PLAYER_VOTE_SECONDS", "30")),
            meeting_cooldown_seconds=int(os.getenv("CODEMAFIA_MEETING_COOLDOWN_SECONDS", "60")),
            allow_draft_content=allow_draft_content,
        ),
        runner_service=app.state.runner_service,
        accept_new_matches=accept_new_matches,
        metrics=app.state.operational_metrics,
        automatic_test_debounce_seconds=float(
            os.getenv("CODEMAFIA_AUTO_TEST_DEBOUNCE_SECONDS", "1.0")
        ),
        reconnect_grace_seconds=int(os.getenv("CODEMAFIA_RECONNECT_GRACE_SECONDS", "60")),
    )
    deadline_stop = asyncio.Event()
    deadline_task: asyncio.Task[None] | None = None
    result_stop = asyncio.Event()
    result_task: asyncio.Task[None] | None = None
    recovery_stop = asyncio.Event()
    recovery_task: asyncio.Task[None] | None = None
    try:
        await app.state.room_coordinator.recover_orphaned_connections()
        await repository.rebuild_game_deadline_index()
        deadline_task = asyncio.create_task(
            DeadlineScheduler(repository, app.state.room_coordinator).run(deadline_stop),
            name="game-deadline-worker",
        )
        if signing_key:
            recovery_task = asyncio.create_task(
                RecoveryWorker(
                    repository, app.state.room_coordinator,
                    runner_timeout_seconds=int(os.getenv("CODEMAFIA_RUNNER_RESULT_TIMEOUT_SECONDS", "45")),
                ).run(recovery_stop),
                name="runner-recovery-worker",
            )
            result_processor = RunnerResultProcessor(
                repository,
                runner_repository,
                app.state.room_connection_manager,
                signing_key=signing_key,
                room_locks=app.state.room_coordinator.room_locks,
                metrics=app.state.operational_metrics,
            )
            result_task = asyncio.create_task(
                RunnerResultWorker(runner_repository, result_processor).run(result_stop),
                name="runner-result-worker",
            )
        yield
    finally:
        deadline_stop.set()
        result_stop.set()
        recovery_stop.set()
        try:
            await app.state.room_coordinator.close()
            tasks = [task for task in (deadline_task, result_task, recovery_task) if task is not None]
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            await app.state.room_connection_manager.close_all()
            await client.aclose()


app = FastAPI(title="CodeMafia API", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(allowed_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.include_router(room_router)
app.include_router(editor_router)
app.include_router(feedback_router)
app.include_router(websocket_router)


@app.get("/health")
async def health_check(request: Request) -> dict[str, str]:
    try:
        await request.app.state.redis_client.ping()
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="Room storage unavailable.") from exc
    return {"status": "ok"}


@app.get("/ops/metrics", response_class=PlainTextResponse)
async def operational_metrics(request: Request) -> PlainTextResponse:
    configured = metrics_token
    authorization = request.headers.get("authorization", "")
    if not configured or not hmac.compare_digest(
        authorization.encode("utf-8"), f"Bearer {configured}".encode("utf-8")
    ):
        raise HTTPException(status_code=404, detail="Not found.")
    try:
        redis_up = bool(await request.app.state.redis_client.ping())
    except RedisError:
        redis_up = False
    return PlainTextResponse(
        request.app.state.operational_metrics.render(redis_up=redis_up),
        media_type="text/plain; version=0.0.4",
        headers={"Cache-Control": "no-store"},
    )
