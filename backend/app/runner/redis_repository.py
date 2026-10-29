"""Redis Streams transport for bounded runner jobs and result envelopes."""

from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError, ResponseError

from app.runner.contracts import (
    MAX_JOB_BYTES,
    MAX_RESULT_BYTES,
    RunnerEnqueueReceipt,
    RunnerJob,
    RunnerQueueState,
    RunnerResult,
    encode_model,
)
from app.runner.repository import RunnerStorageError


JOB_STREAM = "codemafia:v1:runner:jobs"
RESULT_STREAM = "codemafia:v1:runner:results"
JOB_GROUP = "codemafia-runner-v1"
RESULT_GROUP = "codemafia-api-v1"
JOB_TTL_SECONDS = 3_600
DEDUPE_TTL_SECONDS = JOB_TTL_SECONDS
MAX_QUEUED_JOBS = 500
MAX_RESULT_STREAM_LENGTH = 20_000

_ENQUEUE = """
if redis.call('EXISTS', KEYS[2]) == 1 then
    return {2, redis.call('GET', KEYS[2]), ''}
end
if tonumber(redis.call('XLEN', KEYS[1])) >= tonumber(ARGV[1]) then
    return {0, '', ''}
end
local stream_id = redis.call('XADD', KEYS[1], '*', 'payload', ARGV[2])
redis.call('SET', KEYS[2], ARGV[3], 'EX', tonumber(ARGV[4]), 'NX')
redis.call('SET', KEYS[3], ARGV[2], 'EX', tonumber(ARGV[5]))
return {1, ARGV[3], stream_id}
"""

_ACK_AND_DELETE_JOB = """
redis.call('XACK', KEYS[1], ARGV[1], ARGV[2])
redis.call('XDEL', KEYS[1], ARGV[2])
return 1
"""

_RELEASE_DEDUPE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


def _job_key(run_id: str) -> str:
    if re.fullmatch(r"[0-9a-f]{32}", run_id) is None:
        raise ValueError("Invalid runner run ID.")
    return f"codemafia:v1:runner:job:{run_id}"


def _dedupe_key(value: str) -> str:
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("Invalid runner deduplication key.")
    return f"codemafia:v1:runner:dedupe:{value}"


class RedisRunnerRepository:
    """Atomic enqueue plus consumer-group access to result messages.

    Redis ACLs must restrict job-stream writes to this API and result-stream
    writes to the isolated runner. Redis is transport, never proof that a
    result is trustworthy; the API checks the result HMAC and job identity.
    """

    def __init__(self, client: Redis) -> None:
        self._client = client

    async def enqueue_job(self, job: RunnerJob) -> RunnerEnqueueReceipt:
        payload = encode_model(job, maximum_bytes=MAX_JOB_BYTES)
        try:
            result = await self._client.eval(
                _ENQUEUE,
                3,
                JOB_STREAM,
                _dedupe_key(job.dedupe_key),
                _job_key(job.run_id),
                MAX_QUEUED_JOBS,
                payload,
                job.run_id,
                DEDUPE_TTL_SECONDS,
                JOB_TTL_SECONDS,
            )
        except RedisError as exc:
            raise RunnerStorageError("Runner queue is unavailable.") from exc
        if not isinstance(result, (tuple, list)) or len(result) != 3:
            raise RunnerStorageError("Runner queue returned an invalid receipt.")
        state = int(result[0])
        run_id = result[1].decode() if isinstance(result[1], bytes) else str(result[1])
        stream_id = result[2].decode() if isinstance(result[2], bytes) else str(result[2])
        if state == 0:
            return RunnerEnqueueReceipt(state=RunnerQueueState.FULL)
        if state == 2:
            return RunnerEnqueueReceipt(state=RunnerQueueState.DEDUPLICATED, run_id=run_id)
        if state == 1:
            return RunnerEnqueueReceipt(state=RunnerQueueState.ENQUEUED, run_id=run_id, stream_id=stream_id)
        raise RunnerStorageError("Runner queue returned an unknown status.")

    async def load_job(self, run_id: str) -> RunnerJob | None:
        try:
            raw = await self._client.get(_job_key(run_id))
        except RedisError as exc:
            raise RunnerStorageError("Runner job registry is unavailable.") from exc
        if raw is None:
            return None
        try:
            if len(raw) > MAX_JOB_BYTES:
                raise ValueError("job record exceeds size limit")
            return RunnerJob.model_validate_json(raw)
        except (ValidationError, ValueError, TypeError) as exc:
            raise RunnerStorageError("Stored runner job is invalid.") from exc

    async def release_deduplication(self, job: RunnerJob) -> None:
        """Allow retry after a verified infrastructure failure of this run."""

        try:
            await self._client.eval(
                _RELEASE_DEDUPE, 1, _dedupe_key(job.dedupe_key), job.run_id,
            )
        except RedisError as exc:
            raise RunnerStorageError("Runner retry state is unavailable.") from exc

    async def ensure_job_group(self, group: str = JOB_GROUP) -> None:
        try:
            await self._client.xgroup_create(JOB_STREAM, group, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise RunnerStorageError("Cannot initialize runner job stream.") from exc
        except RedisError as exc:
            raise RunnerStorageError("Cannot initialize runner job stream.") from exc

    async def read_jobs(
        self, *, group: str, consumer: str, count: int = 10, block_ms: int = 5_000
    ) -> tuple[tuple[str, bytes], ...]:
        try:
            streams = await self._client.xreadgroup(
                group, consumer, {JOB_STREAM: ">"}, count=count, block=block_ms,
            )
        except RedisError as exc:
            raise RunnerStorageError("Runner job stream is unavailable.") from exc
        return _extract_messages(streams)

    async def claim_abandoned_jobs(
        self, *, group: str, consumer: str, min_idle_ms: int = 30_000, count: int = 10
    ) -> tuple[tuple[str, bytes], ...]:
        try:
            claimed = await self._client.xautoclaim(
                JOB_STREAM, group, consumer, min_idle_ms, "0-0", count=count,
            )
        except ResponseError as exc:
            raise RunnerStorageError("Redis must support XAUTOCLAIM for job recovery.") from exc
        except RedisError as exc:
            raise RunnerStorageError("Could not recover abandoned runner jobs.") from exc
        entries = claimed[1] if isinstance(claimed, (tuple, list)) and len(claimed) >= 2 else ()
        return _extract_messages([(JOB_STREAM, entries)])

    async def acknowledge_job(self, *, group: str, stream_id: str) -> None:
        try:
            # Job payloads include player code. Remove acknowledged stream rows
            # immediately; the bounded job registry retains only the metadata
            # needed to authenticate a result for its TTL.
            await self._client.eval(_ACK_AND_DELETE_JOB, 1, JOB_STREAM, group, stream_id)
        except RedisError as exc:
            raise RunnerStorageError("Could not acknowledge runner job.") from exc

    async def ensure_result_group(self, group: str = RESULT_GROUP) -> None:
        try:
            await self._client.xgroup_create(RESULT_STREAM, group, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise RunnerStorageError("Cannot initialize runner result stream.") from exc
        except RedisError as exc:
            raise RunnerStorageError("Cannot initialize runner result stream.") from exc

    async def read_results(
        self, *, group: str, consumer: str, count: int = 20, block_ms: int = 1_000
    ) -> tuple[tuple[str, bytes], ...]:
        try:
            streams = await self._client.xreadgroup(
                group, consumer, {RESULT_STREAM: ">"}, count=count, block=block_ms,
            )
        except RedisError as exc:
            raise RunnerStorageError("Runner result stream is unavailable.") from exc
        return _extract_messages(streams)

    async def claim_abandoned_results(
        self, *, group: str, consumer: str, min_idle_ms: int = 30_000, count: int = 20
    ) -> tuple[tuple[str, bytes], ...]:
        try:
            claimed = await self._client.xautoclaim(
                RESULT_STREAM, group, consumer, min_idle_ms, "0-0", count=count,
            )
        except ResponseError as exc:
            # Redis before 6.2 does not support XAUTOCLAIM. Don't quietly
            # discard pending jobs; fail startup so an operator can upgrade.
            raise RunnerStorageError("Redis must support XAUTOCLAIM for result recovery.") from exc
        except RedisError as exc:
            raise RunnerStorageError("Could not recover pending runner results.") from exc
        entries = claimed[1] if isinstance(claimed, (tuple, list)) and len(claimed) >= 2 else ()
        return _extract_messages([(RESULT_STREAM, entries)])

    async def acknowledge_result(self, *, group: str, stream_id: str) -> None:
        try:
            await self._client.xack(RESULT_STREAM, group, stream_id)
        except RedisError as exc:
            raise RunnerStorageError("Could not acknowledge runner result.") from exc

    async def trim_results(self) -> None:
        """Bound retained result history after acknowledgments are durable."""

        try:
            pending = await self._client.xpending(RESULT_STREAM, RESULT_GROUP)
            if int(pending.get("pending", 0)) != 0:
                return
            await self._client.xtrim(RESULT_STREAM, maxlen=MAX_RESULT_STREAM_LENGTH, approximate=True)
        except RedisError as exc:
            raise RunnerStorageError("Could not trim runner result stream.") from exc

    @staticmethod
    def decode_result(raw: bytes) -> RunnerResult:
        if len(raw) > MAX_RESULT_BYTES:
            raise ValueError("Runner result exceeds the size limit.")
        try:
            return RunnerResult.model_validate_json(raw)
        except (ValidationError, ValueError, TypeError) as exc:
            raise ValueError("Runner result is malformed.") from exc


def _extract_messages(streams: Any) -> tuple[tuple[str, bytes], ...]:
    result: list[tuple[str, bytes]] = []
    try:
        for _, entries in streams or ():
            for stream_id, fields in entries:
                payload = fields.get(b"payload", fields.get("payload"))
                if isinstance(payload, str):
                    payload = payload.encode("utf-8")
                if not isinstance(payload, bytes):
                    # Preserve malformed stream rows so the consumer can
                    # classify and acknowledge them instead of leaving poison
                    # entries permanently pending.
                    payload = b""
                result.append((stream_id.decode() if isinstance(stream_id, bytes) else str(stream_id), payload))
    except (TypeError, ValueError, AttributeError) as exc:
        raise RunnerStorageError("Runner result stream has an invalid shape.") from exc
    return tuple(result)
