"""Storage boundary for runner jobs and their untrusted result messages.

The API writes immutable jobs. A separately isolated runner consumes them and
publishes result envelopes. The API validates every result before game rules
can observe it.
"""

from __future__ import annotations

from typing import Protocol

from app.runner.contracts import RunnerEnqueueReceipt, RunnerJob, RunnerResult


class RunnerStorageError(RuntimeError):
    """The runner streams or Redis job registry cannot be accessed safely."""


class RunnerRepository(Protocol):
    async def enqueue_job(self, job: RunnerJob) -> RunnerEnqueueReceipt: ...

    async def load_job(self, run_id: str) -> RunnerJob | None: ...

    async def release_deduplication(self, job: RunnerJob) -> None: ...

    async def ensure_job_group(self, group: str) -> None: ...

    async def read_jobs(
        self, *, group: str, consumer: str, count: int, block_ms: int
    ) -> tuple[tuple[str, bytes], ...]: ...

    async def claim_abandoned_jobs(
        self, *, group: str, consumer: str, min_idle_ms: int, count: int
    ) -> tuple[tuple[str, bytes], ...]: ...

    async def acknowledge_job(self, *, group: str, stream_id: str) -> None: ...

    async def ensure_result_group(self, group: str) -> None: ...

    async def read_results(
        self, *, group: str, consumer: str, count: int, block_ms: int
    ) -> tuple[tuple[str, bytes], ...]: ...

    async def claim_abandoned_results(
        self, *, group: str, consumer: str, min_idle_ms: int, count: int
    ) -> tuple[tuple[str, bytes], ...]: ...

    async def acknowledge_result(self, *, group: str, stream_id: str) -> None: ...

    async def decode_result(self, raw: bytes) -> RunnerResult: ...
