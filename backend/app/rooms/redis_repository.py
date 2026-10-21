"""Redis-backed active rooms and guest-session lookup for one API writer."""

from __future__ import annotations

import json
import math
from datetime import datetime

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.game.models import RoomState
from app.rooms.repository import GuestSession, RoomStorageError, StoredRoom
from app.rooms.serialization import deserialize_room, serialize_room


_CREATE_ROOM = """
if redis.call('EXISTS', KEYS[1]) == 1 or redis.call('EXISTS', KEYS[2]) == 1 then
    return 0
end
redis.call('SET', KEYS[1], ARGV[1], 'EXAT', tonumber(ARGV[3]))
redis.call('SET', KEYS[2], ARGV[2], 'EXAT', tonumber(ARGV[4]))
return 1
"""

_COMPARE_AND_SWAP = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then
    return 0
end
if ARGV[6] == '1' and redis.call('EXISTS', KEYS[2]) == 1 then
    return 0
end
if ARGV[7] == '1' and redis.call('EXISTS', KEYS[3]) == 0 then
    return 0
end
redis.call('SET', KEYS[1], ARGV[2], 'EXAT', tonumber(ARGV[4]))
if ARGV[6] == '1' then
    redis.call('SET', KEYS[2], ARGV[3], 'EXAT', tonumber(ARGV[5]))
end
if ARGV[7] == '1' then
    redis.call('DEL', KEYS[3])
end
return 1
"""

_JOIN_LIMIT = """
local attempts = redis.call('INCR', KEYS[1])
if attempts == 1 then
    redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]))
end
return attempts <= tonumber(ARGV[2]) and 1 or 0
"""


def _expiry_second(value: datetime) -> int:
    return math.ceil(value.timestamp())


def _room_key(code: str) -> str:
    return f"codemafia:v1:room:{code}"


def _session_key(credential_hash: str) -> str:
    return f"codemafia:v1:guest:{credential_hash}"


def _session_value(session: GuestSession) -> bytes:
    return json.dumps(
        {
            "room_code": session.room_code,
            "player_id": session.player_id,
            "expires_at": session.expires_at.isoformat(),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class RedisRoomRepository:
    """Atomic room/session writes; no Redis details reach the game engine."""

    def __init__(self, client: Redis) -> None:
        self._client = client

    async def create_room(self, state: RoomState, session: GuestSession) -> bool:
        if session.room_code != state.room_code:
            raise ValueError("Session and room codes must match.")
        try:
            result = await self._client.eval(
                _CREATE_ROOM,
                2,
                _room_key(state.room_code),
                _session_key(session.credential_hash),
                serialize_room(state),
                _session_value(session),
                _expiry_second(state.expires_at),
                _expiry_second(session.expires_at),
            )
            return result == 1
        except RedisError as exc:
            raise RoomStorageError("Room storage is unavailable.") from exc

    async def load_room(self, room_code: str) -> StoredRoom | None:
        try:
            raw = await self._client.get(_room_key(room_code))
        except RedisError as exc:
            raise RoomStorageError("Room storage is unavailable.") from exc
        if raw is None:
            return None
        if not isinstance(raw, bytes):
            raise RoomStorageError("Redis must return byte-valued room records.")
        return StoredRoom(state=deserialize_room(raw), raw=raw)

    async def load_session(self, credential_hash: str) -> GuestSession | None:
        try:
            raw = await self._client.get(_session_key(credential_hash))
        except RedisError as exc:
            raise RoomStorageError("Room storage is unavailable.") from exc
        if raw is None:
            return None
        try:
            value = json.loads(raw)
            return GuestSession(
                credential_hash=credential_hash,
                room_code=value["room_code"],
                player_id=value["player_id"],
                expires_at=datetime.fromisoformat(value["expires_at"]),
            )
        except (ValueError, TypeError, KeyError) as exc:
            raise RoomStorageError("Stored guest session is invalid.") from exc

    async def compare_and_swap(
        self,
        previous: StoredRoom,
        updated: RoomState,
        *,
        new_session: GuestSession | None = None,
        revoke_credential_hash: str | None = None,
    ) -> bool:
        if updated.room_code != previous.state.room_code:
            raise ValueError("A room update cannot change its room code.")
        if new_session is not None and new_session.room_code != updated.room_code:
            raise ValueError("New session belongs to another room.")
        new_key = _session_key(new_session.credential_hash) if new_session else "codemafia:v1:unused:new"
        old_key = _session_key(revoke_credential_hash) if revoke_credential_hash else "codemafia:v1:unused:old"
        try:
            result = await self._client.eval(
                _COMPARE_AND_SWAP,
                3,
                _room_key(updated.room_code),
                new_key,
                old_key,
                previous.raw,
                serialize_room(updated),
                _session_value(new_session) if new_session else b"",
                _expiry_second(updated.expires_at),
                _expiry_second(new_session.expires_at) if new_session else 0,
                "1" if new_session else "0",
                "1" if revoke_credential_hash else "0",
            )
            return result == 1
        except RedisError as exc:
            raise RoomStorageError("Room storage is unavailable.") from exc

    async def revoke_session(self, credential_hash: str) -> None:
        try:
            await self._client.delete(_session_key(credential_hash))
        except RedisError as exc:
            raise RoomStorageError("Room storage is unavailable.") from exc

    async def allow_join_attempt(
        self, subject_hash: str, *, window_seconds: int, max_attempts: int
    ) -> bool:
        key = f"codemafia:v1:join-limit:{subject_hash}"
        try:
            result = await self._client.eval(
                _JOIN_LIMIT, 1, key, window_seconds, max_attempts
            )
            return result == 1
        except RedisError as exc:
            raise RoomStorageError("Room storage is unavailable.") from exc
