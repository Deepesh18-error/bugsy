"""Storage contract for one active room and its opaque guest sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import re
from typing import Protocol

from app.game.models import RoomState


class RoomStorageError(Exception):
    """Redis is unavailable or a stored room cannot be safely decoded."""


@dataclass(frozen=True, slots=True)
class ScheduledCategoryDeadline:
    room_code: str
    deadline_id: str
    due_at: datetime

    def __post_init__(self) -> None:
        if not self.room_code or not self.deadline_id:
            raise ValueError("Scheduled deadlines require room and deadline IDs.")
        if self.due_at.tzinfo is None or self.due_at.utcoffset() != timedelta(0):
            raise ValueError("Scheduled deadline time must use UTC.")


@dataclass(frozen=True, slots=True)
class StoredRoom:
    state: RoomState
    raw: bytes
    sequence: int = 0
    receipts: tuple[CommandReceipt, ...] = ()


@dataclass(frozen=True, slots=True)
class CommandReceipt:
    player_id: str
    request_id: str
    fingerprint: str
    sequence: int
    accepted: bool
    code: str | None
    message: str | None
    recorded_at: datetime

    def __post_init__(self) -> None:
        if (
            not isinstance(self.player_id, str) or not self.player_id
            or not isinstance(self.request_id, str) or not self.request_id
        ):
            raise ValueError("Receipt player and request IDs are required.")
        if len(self.player_id) > 128 or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", self.request_id) is None:
            raise ValueError("Receipt identity is invalid.")
        if not isinstance(self.fingerprint, str) or re.fullmatch(r"[0-9a-f]{64}", self.fingerprint) is None:
            raise ValueError("Receipt fingerprint must be a SHA-256 hex digest.")
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("Receipt sequence must be non-negative.")
        if type(self.accepted) is not bool:
            raise ValueError("Receipt acceptance must be a boolean.")
        if self.accepted and (self.code is not None or self.message is not None):
            raise ValueError("Accepted receipts cannot contain an error.")
        if not self.accepted and (
            not isinstance(self.code, str) or not self.code
            or not isinstance(self.message, str) or not self.message
        ):
            raise ValueError("Rejected receipts require an error code and message.")
        if not self.accepted and (
            re.fullmatch(r"[A-Za-z0-9._-]{1,128}", self.code) is None
            or len(self.message) > 160
        ):
            raise ValueError("Rejected receipt error is invalid.")
        if (
            not isinstance(self.recorded_at, datetime)
            or self.recorded_at.tzinfo is None
            or self.recorded_at.utcoffset() != timedelta(0)
        ):
            raise ValueError("Receipt time must be UTC.")


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

    async def load_command_receipt(
        self, room_code: str, player_id: str, request_id: str
    ) -> CommandReceipt | None: ...

    async def compare_and_swap(
        self,
        previous: StoredRoom,
        updated: RoomState,
        *,
        new_session: GuestSession | None = None,
        revoke_credential_hash: str | None = None,
        receipt: CommandReceipt | None = None,
        advance_sequence: bool = False,
    ) -> bool: ...

    async def revoke_session(self, credential_hash: str) -> None: ...

    async def allow_join_attempt(
        self, subject_hash: str, *, window_seconds: int, max_attempts: int
    ) -> bool: ...

    async def due_category_deadlines(
        self, now: datetime, *, limit: int
    ) -> tuple[ScheduledCategoryDeadline, ...]: ...

    async def remove_category_deadline(
        self, room_code: str, deadline_id: str
    ) -> None: ...

    async def rebuild_category_deadline_index(self) -> None: ...

    async def load_editor_document(self, document_id: str) -> dict | None: ...

    async def initialize_editor_document(
        self, previous: StoredRoom, *, document_id: str, source: str, y_state: str,
    ) -> bool: ...

    async def commit_editor_document(
        self, previous: StoredRoom, updated: RoomState, *, document_id: str,
        previous_revision_id: str, revision_id: str, source: str,
        y_state: str, author_player_id: str, recorded_at: datetime,
    ) -> bool: ...
