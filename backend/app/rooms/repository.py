"""Storage contract for one active room and its opaque guest sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from app.game.models import RoomState


class RoomStorageError(Exception):
    """Redis is unavailable or a stored room cannot be safely decoded."""


@dataclass(frozen=True, slots=True)
class StoredRoom:
    state: RoomState
    raw: bytes


@dataclass(frozen=True, slots=True)
class GuestSession:
    credential_hash: str
    room_code: str
    player_id: str
    expires_at: datetime

    def __post_init__(self) -> None:
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() != timedelta(0):
            raise ValueError("Guest-session expiry must be UTC.")


class RoomRepository(Protocol):
    """All multi-key changes must be atomic in the concrete implementation."""

    async def create_room(self, state: RoomState, session: GuestSession) -> bool: ...

    async def load_room(self, room_code: str) -> StoredRoom | None: ...

    async def load_session(self, credential_hash: str) -> GuestSession | None: ...

    async def compare_and_swap(
        self,
        previous: StoredRoom,
        updated: RoomState,
        *,
        new_session: GuestSession | None = None,
        revoke_credential_hash: str | None = None,
    ) -> bool: ...

    async def revoke_session(self, credential_hash: str) -> None: ...

    async def allow_join_attempt(
        self, subject_hash: str, *, window_seconds: int, max_attempts: int
    ) -> bool: ...
