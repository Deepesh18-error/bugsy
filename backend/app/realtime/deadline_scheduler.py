"""Retryable vote, reveal, and coding deadline worker.

The Redis repository supplies a durable deadline index and the API lifespan
starts this worker. Process-local timers would lose pending transitions after
an API restart.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from enum import Enum
from math import isfinite
from typing import Protocol

from app.game.deadlines import require_utc_time
from app.rooms.repository import RoomStorageError, ScheduledGameDeadline


logger = logging.getLogger(__name__)


class DeadlineAttempt(str, Enum):
    COMMITTED = "committed"
    STALE = "stale"
    NOT_DUE = "not_due"
    RETRY = "retry"


class GameDeadlineIndex(Protocol):
    """Durable source implemented by the Redis room repository."""

    async def due_game_deadlines(
        self, now: datetime, *, limit: int
    ) -> tuple[ScheduledGameDeadline, ...]: ...

    async def remove_game_deadline(
        self, room_code: str, deadline_id: str
    ) -> None: ...


class GameDeadlineResolver(Protocol):
    async def resolve_game_deadline(
        self, room_code: str, deadline_id: str
    ) -> DeadlineAttempt: ...


# Kept as aliases while callers transition from the setup-only scheduler.
CategoryDeadlineIndex = GameDeadlineIndex
CategoryDeadlineResolver = GameDeadlineResolver


class DeadlineScheduler:
    """Poll due entries and leave failed work in the index for retry.

    The coordinator checks the current room deadline ID under its room lock and
    Redis CAS. A crash after committing but before removing an index entry is
    safe: replay sees STALE and removes only that old deadline ID.
    """

    def __init__(
        self,
        index: GameDeadlineIndex,
        resolver: GameDeadlineResolver,
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
        lookup = getattr(self._index, "due_game_deadlines", None)
        if lookup is None:
            lookup = getattr(self._index, "due_category_deadlines")
        entries = await lookup(now, limit=self._batch_size)
        completed = 0
        for entry in entries:
            if entry.due_at > now:
                continue
            resolve = getattr(self._resolver, "resolve_game_deadline", None)
            if resolve is None:
                resolve = getattr(self._resolver, "resolve_category_deadline")
            outcome = await resolve(entry.room_code, entry.deadline_id)
            if outcome in {DeadlineAttempt.COMMITTED, DeadlineAttempt.STALE}:
                remove = getattr(self._index, "remove_game_deadline", None)
                if remove is None:
                    remove = getattr(self._index, "remove_category_deadline")
                await remove(entry.room_code, entry.deadline_id)
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
                logger.exception("Could not process game deadlines; retrying")
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._poll_seconds)
            except asyncio.TimeoutError:
                pass
