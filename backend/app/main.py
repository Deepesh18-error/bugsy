"""FastAPI composition root; room rules and Redis are separate packages."""

from contextlib import asynccontextmanager
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.api.rooms import router as room_router
from app.api.websocket import RoomConnectionManager, router as websocket_router
from app.rooms.redis_repository import RedisRoomRepository
from app.rooms.service import RoomPolicy, RoomService


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
secure_guest_cookie = os.getenv(
    "CODEMAFIA_SECURE_COOKIE", "true" if environment == "production" else "false"
).lower() == "true"
guest_cookie_samesite = os.getenv("CODEMAFIA_COOKIE_SAMESITE", "lax").lower()
if guest_cookie_samesite not in {"lax", "strict", "none"}:
    raise ValueError("Guest-cookie SameSite must be lax, strict, or none.")
if guest_cookie_samesite == "none" and not secure_guest_cookie:
    raise ValueError("Cross-site guest cookies require Secure mode and HTTPS.")
if environment == "production" and not secure_guest_cookie:
    raise ValueError("Production guest cookies must use HTTPS-only Secure mode.")


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
    app.state.room_service = RoomService(
        RedisRoomRepository(client),
        policy=RoomPolicy(
            room_ttl_seconds=int(os.getenv("CODEMAFIA_ROOM_TTL_SECONDS", "3600")),
            credential_ttl_seconds=int(os.getenv("CODEMAFIA_CREDENTIAL_TTL_SECONDS", "3600")),
            join_window_seconds=int(os.getenv("CODEMAFIA_JOIN_WINDOW_SECONDS", "60")),
            max_join_attempts=int(os.getenv("CODEMAFIA_MAX_JOIN_ATTEMPTS", "30")),
        ),
    )
    app.state.room_connection_manager = RoomConnectionManager()
    # The command coordinator is a later Phase 6 increment. Until it is
    # installed, the gateway validates commands and rejects them explicitly.
    app.state.room_coordinator = None
    try:
        yield
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
app.include_router(websocket_router)


@app.get("/health")
async def health_check(request: Request) -> dict[str, str]:
    try:
        await request.app.state.redis_client.ping()
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="Room storage unavailable.") from exc
    return {"status": "ok"}
