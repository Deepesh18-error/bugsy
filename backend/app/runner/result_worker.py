"""Lifecycle loop for consuming isolated-runner results without blocking APIs."""

from __future__ import annotations

import asyncio
import logging
import secrets

from app.runner.redis_repository import RESULT_GROUP, RedisRunnerRepository
from app.runner.repository import RunnerStorageError
from app.runner.result_processor import InvalidRunnerMessage, RunnerResultProcessor


logger = logging.getLogger(__name__)


class RunnerResultWorker:
    def __init__(
        self,
        repository: RedisRunnerRepository,
        processor: RunnerResultProcessor,
        *,
        group: str = RESULT_GROUP,
        consumer: str | None = None,
        batch_size: int = 20,
        block_ms: int = 1_000,
        claim_idle_ms: int = 30_000,
    ) -> None:
        if batch_size < 1 or block_ms < 0 or claim_idle_ms < 1:
            raise ValueError("Runner worker bounds must be positive.")
        self._repository = repository
        self._processor = processor
        self._group = group
        self._consumer = consumer or f"api-{secrets.token_hex(8)}"
        self._batch_size = batch_size
        self._block_ms = block_ms
        self._claim_idle_ms = claim_idle_ms

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self._repository.ensure_result_group(self._group)
                messages = await self._repository.claim_abandoned_results(
                    group=self._group, consumer=self._consumer,
                    min_idle_ms=self._claim_idle_ms, count=self._batch_size,
                )
                if not messages:
                    messages = await self._repository.read_results(
                        group=self._group, consumer=self._consumer,
                        count=self._batch_size, block_ms=self._block_ms,
                    )
                for stream_id, payload in messages:
                    await self._handle_message(stream_id, payload)
            except asyncio.CancelledError:
                raise
            except RunnerStorageError:
                logger.warning("Runner result storage is unavailable; retrying.")
                await _wait_or_stop(stop, 1.0)
            except Exception as exc:
                logger.error("Unexpected runner result worker error (%s); retrying.", type(exc).__name__)
                await _wait_or_stop(stop, 1.0)

    async def _handle_message(self, stream_id: str, payload: bytes) -> None:
        try:
            result = self._repository.decode_result(payload)
        except ValueError:
            logger.warning("Discarding a malformed runner result envelope.")
            await self._repository.acknowledge_result(group=self._group, stream_id=stream_id)
            return
        try:
            terminal = await self._processor.process(result)
        except InvalidRunnerMessage:
            # Poison, forged, or mismatched messages are terminal. Never loop
            # forever on attacker-controlled data; do not log source or result.
            logger.warning("Discarding an invalid runner result envelope.")
            await self._repository.acknowledge_result(group=self._group, stream_id=stream_id)
            return
        except Exception as exc:
            # Leave pending so another worker/restart can recover transient
            # room-store failures. Unexpected application errors get the same
            # retry behavior, and remain visible in logs without payload data.
            logger.error("Runner result processing failed (%s); leaving it pending.", type(exc).__name__)
            return
        if not terminal:
            return
        await self._repository.acknowledge_result(group=self._group, stream_id=stream_id)
        await self._repository.trim_results()


async def _wait_or_stop(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except TimeoutError:
        pass
