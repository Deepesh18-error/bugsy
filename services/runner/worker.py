"""Bounded Redis worker that signs verdicts from trusted tests only."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import secrets
import signal
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError, ResponseError

from challenges.registry import resolve_job
from contracts import RunnerStatus, decode_job, make_signed_result
from executor import RunnerExecutor, RunnerInfrastructureError


logger = logging.getLogger(__name__)
JOB_STREAM = "codemafia:v1:runner:jobs"
RESULT_STREAM = "codemafia:v1:runner:results"
RESULT_CAP = 20_000
PUBLISH_TTL_SECONDS = 3_600
CLAIM_IDLE_MS = 120_000

_PUBLISH_ONCE = """
local prior = redis.call('GET', KEYS[2])
if prior then return prior end
if tonumber(redis.call('XLEN', KEYS[1])) >= tonumber(ARGV[2]) then return '' end
local stream_id = redis.call('XADD', KEYS[1], '*', 'payload', ARGV[1])
redis.call('SET', KEYS[2], stream_id, 'EX', tonumber(ARGV[3]))
return stream_id
"""

_ACK_AND_DELETE = """
redis.call('XACK', KEYS[1], ARGV[1], ARGV[2])
redis.call('XDEL', KEYS[1], ARGV[2])
return 1
"""


class WorkerSettings:
    def __init__(self) -> None:
        self.redis_url = os.environ.get("REDIS_URL", "")
        self.signing_key = os.environ.get("CODEMAFIA_RUNNER_RESULT_HMAC_KEY", "")
        self.group = os.environ.get("CODEMAFIA_RUNNER_CONSUMER_GROUP", "codemafia-runner-v1")
        self.runs_dir = Path(os.environ.get("CODEMAFIA_RUNNER_RUNS_DIR", "/runs"))
        try:
            self.concurrency = int(os.environ.get("CODEMAFIA_RUNNER_MAX_CONCURRENCY", "2"))
        except ValueError as exc:
            raise ValueError("runner concurrency must be an integer") from exc
        if not self.redis_url.startswith(("redis://", "rediss://")):
            raise ValueError("REDIS_URL must point to Redis")
        if len(self.signing_key.encode("utf-8")) < 32:
            raise ValueError("the runner result signing key must contain at least 32 bytes")
        if not 1 <= self.concurrency <= 4:
            raise ValueError("runner concurrency must be between 1 and 4")
        if not self.group or len(self.group) > 80:
            raise ValueError("runner consumer group is invalid")


class RunnerWorker:
    def __init__(self, redis: Redis, executor: RunnerExecutor, settings: WorkerSettings) -> None:
        self._redis = redis
        self._executor = executor
        self._settings = settings
        self._consumer = f"runner-{secrets.token_hex(8)}"

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self._ensure_group()
                messages = await self._claim_abandoned()
                if not messages:
                    messages = await self._read_new()
                if messages:
                    # The batch itself is bounded by concurrency. A new batch
                    # starts only after all current executions have finished.
                    await asyncio.gather(*(self._process(stream_id, raw)
                                           for stream_id, raw in messages))
            except asyncio.CancelledError:
                raise
            except RedisError:
                logger.warning("Runner queue unavailable; retrying.")
                await _wait_or_stop(stop, 1.0)
            except Exception as exc:
                logger.error("Runner worker loop failed (%s); retrying.", type(exc).__name__)
                await _wait_or_stop(stop, 1.0)

    async def _ensure_group(self) -> None:
        try:
            await self._redis.xgroup_create(JOB_STREAM, self._settings.group, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def _claim_abandoned(self) -> tuple[tuple[str, bytes], ...]:
        response = await self._redis.xautoclaim(
            JOB_STREAM, self._settings.group, self._consumer,
            CLAIM_IDLE_MS, "0-0", count=self._settings.concurrency,
        )
        return _messages(response[1])

    async def _read_new(self) -> tuple[tuple[str, bytes], ...]:
        response = await self._redis.xreadgroup(
            self._settings.group, self._consumer, {JOB_STREAM: ">"},
            count=self._settings.concurrency, block=3_000,
        )
        return _messages(response[0][1]) if response else ()

    async def _process(self, stream_id: str, raw: bytes) -> None:
        try:
            job = decode_job(raw)
        except ValueError:
            logger.warning("Discarding malformed runner job message.")
            await self._acknowledge(stream_id)
            return

        published_key = f"codemafia:v1:runner:published:{job.run_id}"
        running_key = f"codemafia:v1:runner:running:{job.run_id}"
        try:
            if await self._redis.exists(published_key):
                await self._acknowledge(stream_id)
                return
            started_at = datetime.now(timezone.utc)
            if not await self._redis.exists(running_key):
                running_result = make_signed_result(
                    job,
                    status=RunnerStatus.RUNNING,
                    started_at=started_at,
                    completed_at=started_at,
                    tests=(),
                    signing_key=self._settings.signing_key,
                )
                status_stream_id = await self._redis.eval(
                    _PUBLISH_ONCE, 2, RESULT_STREAM, running_key,
                    running_result, RESULT_CAP, PUBLISH_TTL_SECONDS,
                )
                if not status_stream_id:
                    logger.warning("Runner status stream is at capacity; job remains pending.")
                    return
            try:
                challenge = resolve_job(job)
                tests = await self._executor.execute(job, challenge)
                status = RunnerStatus.COMPLETED
            except (ValueError, RunnerInfrastructureError):
                # Unknown pinned content or an unavailable jail cannot turn
                # into passing test verdicts.
                tests = ()
                status = RunnerStatus.RUNNER_ERROR
            except Exception as exc:
                logger.error("Trusted runner execution failed for run %s (%s).", job.run_id, type(exc).__name__)
                tests = ()
                status = RunnerStatus.RUNNER_ERROR
            completed_at = datetime.now(timezone.utc)
            result = make_signed_result(
                job, status=status, started_at=started_at, completed_at=completed_at,
                tests=tests, signing_key=self._settings.signing_key,
            )
            stream_result = await self._redis.eval(
                _PUBLISH_ONCE, 2, RESULT_STREAM, published_key,
                result, RESULT_CAP, PUBLISH_TTL_SECONDS,
            )
            if not stream_result:
                logger.warning("Runner result stream is at capacity; job remains pending.")
                return
            await self._acknowledge(stream_id)
        except RedisError:
            logger.warning("Could not publish runner result; job remains pending.")

    async def _acknowledge(self, stream_id: str) -> None:
        await self._redis.eval(_ACK_AND_DELETE, 1, JOB_STREAM, self._settings.group, stream_id)


def _messages(entries: Any) -> tuple[tuple[str, bytes], ...]:
    result: list[tuple[str, bytes]] = []
    for stream_id, fields in entries or ():
        payload = fields.get(b"payload", fields.get("payload"))
        if not isinstance(payload, bytes):
            payload = b""
        result.append((stream_id.decode("ascii") if isinstance(stream_id, bytes) else str(stream_id), payload))
    return tuple(result)


async def _wait_or_stop(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except TimeoutError:
        pass


async def main() -> None:
    settings = WorkerSettings()
    executor = RunnerExecutor(settings.runs_dir)
    await executor.preflight()
    redis = Redis.from_url(settings.redis_url, decode_responses=False,
                           socket_connect_timeout=2, socket_timeout=8)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(name, stop.set)
    try:
        await RunnerWorker(redis, executor, settings).run(stop)
    finally:
        await redis.aclose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(main())
