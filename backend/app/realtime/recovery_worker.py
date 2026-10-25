"""Recover official runs abandoned by a stopped or unavailable runner."""

from __future__ import annotations

import asyncio
import logging

from app.realtime.coordinator import RoomCoordinator
from app.rooms.repository import RoomRepository, RoomStorageError


logger = logging.getLogger(__name__)


class RecoveryWorker:
    def __init__(self, rooms: RoomRepository, coordinator: RoomCoordinator, *,
                 runner_timeout_seconds: int = 45, poll_seconds: float = 5.0) -> None:
        if type(runner_timeout_seconds) is not int or runner_timeout_seconds <= 0 or poll_seconds <= 0:
            raise ValueError("Recovery intervals must be positive.")
        self._rooms = rooms
        self._coordinator = coordinator
        self._runner_timeout_seconds = runner_timeout_seconds
        self._poll_seconds = poll_seconds

    async def process_once(self) -> int:
        expired = 0
        for room_code in await self._rooms.list_room_codes():
            expired += await self._coordinator.expire_stale_official_runs(
                room_code, timeout_seconds=self._runner_timeout_seconds,
            )
        return expired

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self.process_once()
            except RoomStorageError:
                logger.exception("Room storage is unavailable; retrying recovery.")
            except Exception:
                logger.exception("Runner recovery failed; retrying.")
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._poll_seconds)
            except asyncio.TimeoutError:
                pass
