"""Create, join, resume, and leave rooms without HTTP or Redis coupling."""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from app.game.commands import LeaveRoom
from app.game.models import ConnectionStatus, GamePhase, PlayerState, RoomState
from app.game.outcomes import TransitionAccepted
from app.game.transitions import apply_command, restore_player_connection
from app.rooms.identity import (
    credential_digest,
    display_name_key,
    new_player_id,
    new_reconnect_credential,
    new_room_code,
    normalize_display_name,
    normalize_room_code,
)
from app.rooms.repository import GuestSession, RoomRepository


@dataclass(frozen=True, slots=True)
class RoomPolicy:
    room_ttl_seconds: int = 3600
    credential_ttl_seconds: int = 3600
    join_window_seconds: int = 60
    max_join_attempts: int = 30

    def __post_init__(self) -> None:
        if min(
            self.room_ttl_seconds,
            self.credential_ttl_seconds,
            self.join_window_seconds,
            self.max_join_attempts,
        ) <= 0:
            raise ValueError("Room durations and attempt limits must be positive.")


@dataclass(frozen=True, slots=True)
class GuestResult:
    state: RoomState
    player_id: str
    credential: str
    credential_expires_at: datetime


@dataclass(frozen=True, slots=True)
class AuthenticatedGuest:
    """Read-only guest identity for a WebSocket connection.

    Unlike HTTP resume, authentication does not rotate the cookie. A WebSocket
    handshake cannot reliably deliver a replacement browser cookie.
    """

    state: RoomState
    player_id: str
    credential_expires_at: datetime
    sequence: int = 0


class RoomServiceError(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _unavailable() -> RoomServiceError:
    # Invalid, absent, expired, and closed codes share one public response.
    return RoomServiceError("ROOM_UNAVAILABLE", "Room is unavailable.", 404)


def _invalid_session() -> RoomServiceError:
    return RoomServiceError("SESSION_INVALID", "Guest session is invalid or expired.", 401)


def _checked_credential_hash(credential: str | None) -> str:
    if not isinstance(credential, str) or re.fullmatch(r"[A-Za-z0-9_-]{43}", credential) is None:
        raise _invalid_session()
    return credential_digest(credential)


class RoomService:
    def __init__(
        self,
        repository: RoomRepository,
        *,
        policy: RoomPolicy | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._policy = policy or RoomPolicy()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self) -> datetime:
        return self._clock()

    def _session(self, room: RoomState, player_id: str, credential: str, now: datetime) -> GuestSession:
        return GuestSession(
            credential_hash=credential_digest(credential),
            room_code=room.room_code,
            player_id=player_id,
            expires_at=min(
                room.expires_at,
                now + timedelta(seconds=self._policy.credential_ttl_seconds),
            ),
        )

    async def create_room(self, display_name: str, capacity: int = 5) -> GuestResult:
        name = normalize_display_name(display_name)
        if capacity not in (4, 5):
            raise RoomServiceError("INVALID_CAPACITY", "Capacity must be four or five.", 422)
        now = self._now()
        for _ in range(12):
            player_id = new_player_id()
            room = RoomState(
                room_code=new_room_code(),
                host_player_id=player_id,
                players=(PlayerState(player_id=player_id, display_name=name, joined_at=now),),
                created_at=now,
                expires_at=now + timedelta(seconds=self._policy.room_ttl_seconds),
                capacity=capacity,
                phase=GamePhase.LOBBY,
            )
            credential = new_reconnect_credential()
            session = self._session(room, player_id, credential, now)
            if await self._repository.create_room(room, session):
                return GuestResult(room, player_id, credential, session.expires_at)
        raise RoomServiceError("ROOM_ALLOCATION_FAILED", "Could not allocate a room.", 503)

    async def join_room(
        self, room_code: str, display_name: str, *, join_subject: str
    ) -> GuestResult:
        subject_hash = hashlib.sha256(join_subject.encode("utf-8")).hexdigest()
        allowed = await self._repository.allow_join_attempt(
            subject_hash,
            window_seconds=self._policy.join_window_seconds,
            max_attempts=self._policy.max_join_attempts,
        )
        if not allowed:
            raise RoomServiceError("RATE_LIMITED", "Too many join attempts. Try later.", 429)
        code = normalize_room_code(room_code)
        if code is None:
            raise _unavailable()
        name = normalize_display_name(display_name)
        for _ in range(5):
            stored = await self._repository.load_room(code)
            now = self._now()
            if stored is None or stored.state.is_closed or now >= stored.state.expires_at:
                raise _unavailable()
            room = stored.state
            if room.phase is not GamePhase.LOBBY:
                raise RoomServiceError("ROOM_NOT_JOINABLE", "The match has already started.", 409)
            active = tuple(
                player for player in room.players
                if player.connection is not ConnectionStatus.DEPARTED
            )
            if len(active) >= room.capacity:
                raise RoomServiceError("ROOM_FULL", "Room is full.", 409)
            if any(display_name_key(player.display_name) == name.casefold() for player in active):
                raise RoomServiceError("NAME_TAKEN", "Choose another name in this room.", 409)
            player_id = new_player_id()
            while any(item.player_id == player_id for item in room.players):
                player_id = new_player_id()
            updated = RoomState(
                room_code=room.room_code,
                host_player_id=room.host_player_id,
                players=(*room.players, PlayerState(
                    player_id=player_id, display_name=name, joined_at=now,
                )),
                created_at=room.created_at,
                expires_at=room.expires_at,
                phase=room.phase,
                capacity=room.capacity,
                phase_deadline=room.phase_deadline,
                match=room.match,
                is_closed=room.is_closed,
            )
            credential = new_reconnect_credential()
            session = self._session(updated, player_id, credential, now)
            if await self._repository.compare_and_swap(
                stored, updated, new_session=session
            ):
                return GuestResult(
                    updated, player_id, credential, session.expires_at
                )
        raise RoomServiceError("ROOM_BUSY", "Room changed; please retry.", 409)

    async def resume_player(self, credential: str | None) -> GuestResult:
        digest = _checked_credential_hash(credential)
        for _ in range(5):
            session = await self._repository.load_session(digest)
            now = self._now()
            if session is None or now >= session.expires_at:
                raise _invalid_session()
            stored = await self._repository.load_room(session.room_code)
            if stored is None or stored.state.is_closed or now >= stored.state.expires_at:
                await self._repository.revoke_session(digest)
                raise _invalid_session()
            room = stored.state
            player = next((item for item in room.players if item.player_id == session.player_id), None)
            if player is None or player.connection is ConnectionStatus.DEPARTED:
                await self._repository.revoke_session(digest)
                raise _invalid_session()
            if player.connection is ConnectionStatus.DISCONNECTED:
                restored = restore_player_connection(room, player.player_id, now)
                if not isinstance(restored, TransitionAccepted):
                    await self._repository.revoke_session(digest)
                    raise _invalid_session()
                room = restored.state
            replacement = new_reconnect_credential()
            new_session = self._session(room, player.player_id, replacement, now)
            if await self._repository.compare_and_swap(
                stored, room, new_session=new_session, revoke_credential_hash=digest
            ):
                return GuestResult(
                    room, player.player_id, replacement, new_session.expires_at
                )
        raise _invalid_session()

    async def authenticate_player(self, credential: str | None) -> AuthenticatedGuest:
        """Resolve the current cookie without changing room or session state."""

        digest = _checked_credential_hash(credential)
        session = await self._repository.load_session(digest)
        now = self._now()
        if session is None or now >= session.expires_at:
            raise _invalid_session()
        stored = await self._repository.load_room(session.room_code)
        if stored is None or stored.state.is_closed or now >= stored.state.expires_at:
            raise _invalid_session()
        player = next(
            (item for item in stored.state.players if item.player_id == session.player_id),
            None,
        )
        if player is None or player.connection is ConnectionStatus.DEPARTED:
            raise _invalid_session()
        return AuthenticatedGuest(
            state=stored.state,
            player_id=session.player_id,
            credential_expires_at=session.expires_at,
            sequence=stored.sequence,
        )

    async def leave_room(self, credential: str | None) -> str:
        digest = _checked_credential_hash(credential)
        for _ in range(5):
            session = await self._repository.load_session(digest)
            now = self._now()
            if session is None or now >= session.expires_at:
                raise _invalid_session()
            stored = await self._repository.load_room(session.room_code)
            if stored is None or stored.state.is_closed or now >= stored.state.expires_at:
                await self._repository.revoke_session(digest)
                return session.room_code
            room = stored.state
            player = next((item for item in room.players if item.player_id == session.player_id), None)
            if player is None or player.connection is ConnectionStatus.DEPARTED:
                await self._repository.revoke_session(digest)
                return session.room_code
            if player.connection is ConnectionStatus.DISCONNECTED:
                restored = restore_player_connection(room, player.player_id, now)
                if not isinstance(restored, TransitionAccepted):
                    await self._repository.revoke_session(digest)
                    return session.room_code
                room = restored.state
            outcome = apply_command(
                room,
                LeaveRoom(request_id=secrets.token_urlsafe(16), player_id=player.player_id),
                now,
            )
            if not isinstance(outcome, TransitionAccepted):
                raise RoomServiceError("LEAVE_REJECTED", "Could not leave this room.", 409)
            if await self._repository.compare_and_swap(
                stored, outcome.state, revoke_credential_hash=digest
            ):
                return session.room_code
        raise RoomServiceError("ROOM_BUSY", "Room changed; please retry.", 409)
