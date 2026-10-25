"""Storage contract for one active room and its opaque guest sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import base64
import binascii
import re
from typing import Protocol

from app.game.models import RoomState


class RoomStorageError(Exception):
    """Redis is unavailable or a stored room cannot be safely decoded."""


class EditorStorageLimitError(RoomStorageError):
    """A proposed editor value exceeds its documented storage budget."""


MAX_EDITOR_SOURCE_BYTES = 65_536
MAX_EDITOR_Y_STATE_BYTES = 262_144
MAX_EDITOR_HISTORY_ENTRIES = 30
MAX_EDITOR_HISTORY_BYTES = 1_048_576


def editor_document_id(state: RoomState) -> str | None:
    """One identity per room, match, and round; never reuse a prior document."""

    match = state.match
    current = match.current_round if match is not None else None
    if match is None or match.match_id is None or current is None:
        return None
    return f"{state.room_code}:{match.match_id}:{current.number}"


@dataclass(frozen=True, slots=True)
class EditorRevision:
    revision_id: str
    source: str
    author_player_id: str
    recorded_at: datetime
    restored_from_revision_id: str | None = None

    def __post_init__(self) -> None:
        if (not isinstance(self.revision_id, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", self.revision_id) is None
            or not isinstance(self.author_player_id, str) or not self.author_player_id):
            raise ValueError("Editor revision identity is required.")
        if not isinstance(self.source, str) or len(self.source.encode("utf-8")) > MAX_EDITOR_SOURCE_BYTES:
            raise ValueError("Editor revision source exceeds the size limit.")
        if self.restored_from_revision_id is not None and (
            not isinstance(self.restored_from_revision_id, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", self.restored_from_revision_id) is None
        ):
            raise ValueError("Restore origin must identify a revision.")
        if not isinstance(self.recorded_at, datetime) or self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() != timedelta(0):
            raise ValueError("Editor revision time must use UTC.")


@dataclass(frozen=True, slots=True)
class EditorDocument:
    revision_id: str
    source: str
    y_state: str
    history: tuple[EditorRevision, ...] = ()

    def __post_init__(self) -> None:
        if (not isinstance(self.revision_id, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", self.revision_id) is None):
            raise ValueError("Editor document revision is required.")
        if not isinstance(self.source, str) or len(self.source.encode("utf-8")) > MAX_EDITOR_SOURCE_BYTES:
            raise ValueError("Editor source exceeds the size limit.")
        if not isinstance(self.y_state, str):
            raise ValueError("Editor Yjs state must be base64 text.")
        try:
            raw = base64.b64decode(self.y_state, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("Editor Yjs state is not valid base64.") from exc
        if not raw or len(raw) > MAX_EDITOR_Y_STATE_BYTES:
            raise ValueError("Editor Yjs state exceeds the size limit.")
        if not isinstance(self.history, tuple) or any(not isinstance(item, EditorRevision) for item in self.history):
            raise ValueError("Editor history must contain revision records.")
        if len(self.history) > MAX_EDITOR_HISTORY_ENTRIES:
            raise ValueError("Editor history has too many entries.")
        if sum(len(item.source.encode("utf-8")) for item in self.history) > MAX_EDITOR_HISTORY_BYTES:
            raise ValueError("Editor history exceeds the byte budget.")
        if self.history and self.history[-1].revision_id != self.revision_id:
            raise ValueError("The last history entry must be the current revision.")
        ids = [item.revision_id for item in self.history]
        if len(ids) != len(set(ids)):
            raise ValueError("Editor history has duplicate revision IDs.")

    def append_revision(self, revision: EditorRevision, y_state: str) -> EditorDocument:
        history = [*self.history, revision][-MAX_EDITOR_HISTORY_ENTRIES:]
        while sum(len(item.source.encode("utf-8")) for item in history) > MAX_EDITOR_HISTORY_BYTES:
            history.pop(0)
        return EditorDocument(revision.revision_id, revision.source, y_state, tuple(history))


@dataclass(frozen=True, slots=True)
class ScheduledGameDeadline:
    room_code: str
    deadline_id: str
    due_at: datetime

    def __post_init__(self) -> None:
        if not self.room_code or not self.deadline_id:
            raise ValueError("Scheduled deadlines require room and deadline IDs.")
        if self.due_at.tzinfo is None or self.due_at.utcoffset() != timedelta(0):
            raise ValueError("Scheduled deadline time must use UTC.")


# Kept as an import alias while existing callers migrate to the phase-neutral name.
ScheduledCategoryDeadline = ScheduledGameDeadline


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

    async def due_game_deadlines(
        self, now: datetime, *, limit: int
    ) -> tuple[ScheduledGameDeadline, ...]: ...

    async def remove_game_deadline(
        self, room_code: str, deadline_id: str
    ) -> None: ...

    async def rebuild_game_deadline_index(self) -> None: ...

    async def load_editor_document(self, document_id: str) -> EditorDocument | None: ...

    async def initialize_editor_document(
        self, previous: StoredRoom, *, document_id: str, source: str, y_state: str,
    ) -> bool: ...

    async def commit_editor_document(
        self, previous: StoredRoom, updated: RoomState, *, document_id: str,
        previous_revision_id: str, revision_id: str, source: str,
        y_state: str, author_player_id: str, recorded_at: datetime,
        restored_from_revision_id: str | None = None,
    ) -> bool: ...
