"""Retryable category-vote deadline worker, independent of Redis details.

The durable deadline index and application lifespan will supply this worker in
the repository/main wiring step. Merely keeping asyncio timers in this process
would lose every pending vote when the API restarts.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from math import isfinite
from typing import Protocol

from app.game.deadlines import require_utc_time
from app.rooms.repository import RoomStorageError


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ScheduledCategoryDeadline:
    room_code: str
    deadline_id: str
    due_at: datetime

    def __post_init__(self) -> None:
        if not self.room_code or not self.deadline_id:
            raise ValueError("Scheduled deadlines require room and deadline IDs.")
        require_utc_time(self.due_at)


class DeadlineAttempt(str, Enum):
    COMMITTED = "committed"
    STALE = "stale"
    NOT_DUE = "not_due"
    RETRY = "retry"


class CategoryDeadlineIndex(Protocol):
    """Durable source implemented by the Redis repository in the next step."""

    async def due_category_deadlines(
        self, now: datetime, *, limit: int
    ) -> tuple[ScheduledCategoryDeadline, ...]: ...

    async def remove_category_deadline(
        self, room_code: str, deadline_id: str
    ) -> None: ...


class CategoryDeadlineResolver(Protocol):
    async def resolve_category_deadline(
        self, room_code: str, deadline_id: str
    ) -> DeadlineAttempt: ...


class DeadlineScheduler:
    """Poll due entries and leave failed work in the index for retry.

    The coordinator checks the current room deadline ID under its room lock and
    Redis CAS. A crash after committing but before removing an index entry is
    safe: replay sees STALE and removes only that old deadline ID.
    """

    def __init__(
        self,
        index: CategoryDeadlineIndex,
        resolver: CategoryDeadlineResolver,
        *,
        poll_seconds: float = 0.5,
        batch_size: int = 100,
    ) -> None:
        if (
            isinstance(poll_seconds, bool)
            or not isinstance(poll_seconds, (int, float))
            or not isfinite(poll_seconds)
            or poll_seconds <= 0
            or type(batch_size) is not int
            or batch_size <= 0
        ):
            raise ValueError("Deadline polling interval and batch size must be positive.")
        self._index = index
        self._resolver = resolver
        self._poll_seconds = poll_seconds
        self._batch_size = batch_size

    async def process_due_once(self, now: datetime | None = None) -> int:
        """Return how many due entries were safely completed or discarded."""

        now = now or datetime.now(timezone.utc)
        require_utc_time(now)
        entries = await self._index.due_category_deadlines(now, limit=self._batch_size)
        completed = 0
        for entry in entries:
            if entry.due_at > now:
                continue
            outcome = await self._resolver.resolve_category_deadline(
                entry.room_code, entry.deadline_id
            )
            if outcome in {DeadlineAttempt.COMMITTED, DeadlineAttempt.STALE}:
                await self._index.remove_category_deadline(
                    entry.room_code, entry.deadline_id
                )
                completed += 1
        return completed

    async def run(self, stop: asyncio.Event) -> None:
        """Process persisted deadlines at startup and continue until shutdown."""

        while not stop.is_set():
            try:
                await self.process_due_once()
            except RoomStorageError:
                # Redis outages are transient. Entries remain durable, so the
                # next pass can resume without fabricating a room transition.
                logger.exception("Could not process category deadlines; retrying")
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._poll_seconds)
            except asyncio.TimeoutError:
                pass
