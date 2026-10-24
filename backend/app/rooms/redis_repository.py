"""Redis-backed active rooms and guest-session lookup for one API writer."""

from __future__ import annotations

import json
import math
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.game.models import DeadlineKind, GamePhase, RoomState
from app.game.idempotency import DEFAULT_REQUEST_ID_TTL_SECONDS, durable_receipt_is_live
from app.rooms.repository import (
    CommandReceipt, GuestSession, RoomStorageError,
    ScheduledCategoryDeadline, StoredRoom,
)
from app.rooms.serialization import deserialize_metadata, deserialize_room, serialize_room


_CREATE_ROOM = """
if redis.call('EXISTS', KEYS[1]) == 1 or redis.call('EXISTS', KEYS[2]) == 1 then
    return 0
end
redis.call('SET', KEYS[1], ARGV[1], 'EXAT', tonumber(ARGV[3]))
redis.call('SET', KEYS[2], ARGV[2], 'EXAT', tonumber(ARGV[4]))
if ARGV[5] ~= '' then
    redis.call('ZADD', KEYS[3], tonumber(ARGV[6]), ARGV[5])
end
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
if ARGV[8] == '1' and redis.call('EXISTS', KEYS[4]) == 1 then
    return 0
end
redis.call('SET', KEYS[1], ARGV[2], 'EXAT', tonumber(ARGV[4]))
if ARGV[6] == '1' then
    redis.call('SET', KEYS[2], ARGV[3], 'EXAT', tonumber(ARGV[5]))
end
if ARGV[7] == '1' then
    redis.call('DEL', KEYS[3])
end
if ARGV[8] == '1' then
    redis.call('SET', KEYS[4], ARGV[9], 'EX', tonumber(ARGV[10]))
end
if ARGV[11] ~= '' then
    redis.call('ZREM', KEYS[5], ARGV[11])
end
if ARGV[12] ~= '' then
    redis.call('ZADD', KEYS[5], tonumber(ARGV[13]), ARGV[12])
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

_CATEGORY_DEADLINE_INDEX = "codemafia:v1:category-deadlines"


def _expiry_second(value: datetime) -> int:
    return math.ceil(value.timestamp())


def _room_key(code: str) -> str:
    return f"codemafia:v1:room:{code}"


def _category_deadline_member(state: RoomState) -> tuple[str, float] | None:
    deadline = state.phase_deadline
    if (
        state.is_closed
        or state.phase is not GamePhase.CATEGORY_VOTE
        or deadline is None
        or deadline.kind is not DeadlineKind.CATEGORY_VOTE
    ):
        return None
    return _index_member(state.room_code, deadline.deadline_id), deadline.due_at.timestamp()


def _index_member(room_code: str, deadline_id: str) -> str:
    if not room_code or not deadline_id or ":" in room_code:
        raise ValueError("Invalid category deadline identity.")
    return f"{room_code}:{deadline_id}"


def _session_key(credential_hash: str) -> str:
    return f"codemafia:v1:guest:{credential_hash}"


def _receipt_key(room_code: str, player_id: str, request_id: str) -> str:
    identity = f"{room_code}\0{player_id}\0{request_id}".encode("utf-8")
    return f"codemafia:v1:receipt:{sha256(identity).hexdigest()}"


def _receipt_value(receipt: CommandReceipt) -> bytes:
    return json.dumps(
        asdict(receipt), default=lambda value: value.isoformat(),
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


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
        deadline = _category_deadline_member(state)
        try:
            result = await self._client.eval(
                _CREATE_ROOM,
                3,
                _room_key(state.room_code),
                _session_key(session.credential_hash),
                _CATEGORY_DEADLINE_INDEX,
                serialize_room(state),
                _session_value(session),
                _expiry_second(state.expires_at),
                _expiry_second(session.expires_at),
                deadline[0] if deadline else "",
                deadline[1] if deadline else 0,
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
        sequence, receipts = deserialize_metadata(raw)
        return StoredRoom(state=deserialize_room(raw), raw=raw, sequence=sequence, receipts=receipts)

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

    async def load_command_receipt(
        self, room_code: str, player_id: str, request_id: str
    ) -> CommandReceipt | None:
        try:
            raw = await self._client.get(_receipt_key(room_code, player_id, request_id))
        except RedisError as exc:
            raise RoomStorageError("Room storage is unavailable.") from exc
        if raw is None:
            return None
        try:
            value = json.loads(raw)
            receipt = CommandReceipt(
                player_id=value["player_id"], request_id=value["request_id"],
                fingerprint=value["fingerprint"], sequence=value["sequence"],
                accepted=value["accepted"], code=value["code"],
                message=value["message"], recorded_at=datetime.fromisoformat(value["recorded_at"]),
            )
            if receipt.player_id != player_id or receipt.request_id != request_id:
                raise ValueError("Receipt identity mismatch.")
            return receipt
        except (ValueError, TypeError, KeyError) as exc:
            raise RoomStorageError("Stored command receipt is invalid.") from exc

    async def compare_and_swap(
        self,
        previous: StoredRoom,
        updated: RoomState,
        *,
        new_session: GuestSession | None = None,
        revoke_credential_hash: str | None = None,
        receipt: CommandReceipt | None = None,
        advance_sequence: bool = False,
    ) -> bool:
        if updated.room_code != previous.state.room_code:
            raise ValueError("A room update cannot change its room code.")
        if new_session is not None and new_session.room_code != updated.room_code:
            raise ValueError("New session belongs to another room.")
        new_key = _session_key(new_session.credential_hash) if new_session else "codemafia:v1:unused:new"
        old_key = _session_key(revoke_credential_hash) if revoke_credential_hash else "codemafia:v1:unused:old"
        sequence = previous.sequence + (1 if updated != previous.state or advance_sequence else 0)
        if receipt is not None and receipt.sequence != sequence:
            raise ValueError("Receipt sequence must match the committed room sequence.")
        now = datetime.now(timezone.utc)
        # Preserve only legacy embedded receipts until their original window ends.
        receipts = tuple(
            item for item in previous.receipts
            if durable_receipt_is_live(item.recorded_at, now)
        )
        receipt_key = (
            _receipt_key(updated.room_code, receipt.player_id, receipt.request_id)
            if receipt is not None else "codemafia:v1:unused:receipt"
        )
        prior_deadline = _category_deadline_member(previous.state)
        next_deadline = _category_deadline_member(updated)
        try:
            result = await self._client.eval(
                _COMPARE_AND_SWAP,
                5,
                _room_key(updated.room_code),
                new_key,
                old_key,
                receipt_key,
                _CATEGORY_DEADLINE_INDEX,
                previous.raw,
                serialize_room(updated, sequence=sequence, receipts=receipts),
                _session_value(new_session) if new_session else b"",
                _expiry_second(updated.expires_at),
                _expiry_second(new_session.expires_at) if new_session else 0,
                "1" if new_session else "0",
                "1" if revoke_credential_hash else "0",
                "1" if receipt else "0",
                _receipt_value(receipt) if receipt else b"",
                DEFAULT_REQUEST_ID_TTL_SECONDS,
                prior_deadline[0] if prior_deadline else "",
                next_deadline[0] if next_deadline else "",
                next_deadline[1] if next_deadline else 0,
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

    async def due_category_deadlines(
        self, now: datetime, *, limit: int
    ) -> tuple[ScheduledCategoryDeadline, ...]:
        if now.tzinfo is None or now.utcoffset() is None or now.utcoffset().total_seconds() != 0:
            raise ValueError("Deadline lookup time must use UTC.")
        if type(limit) is not int or limit <= 0:
            raise ValueError("Deadline lookup limit must be positive.")
        try:
            rows = await self._client.zrangebyscore(
                _CATEGORY_DEADLINE_INDEX, "-inf", now.timestamp(),
                start=0, num=limit, withscores=True,
            )
        except RedisError as exc:
            raise RoomStorageError("Deadline index is unavailable.") from exc
        entries = []
        try:
            for raw_member, score in rows:
                room_code, deadline_id = raw_member.decode("ascii").split(":", 1)
                entries.append(ScheduledCategoryDeadline(
                    room_code, deadline_id, datetime.fromtimestamp(score, timezone.utc)
                ))
        except (AttributeError, UnicodeError, ValueError, OverflowError) as exc:
            raise RoomStorageError("Deadline index contains an invalid entry.") from exc
        return tuple(entries)

    async def remove_category_deadline(
        self, room_code: str, deadline_id: str
    ) -> None:
        try:
            await self._client.zrem(
                _CATEGORY_DEADLINE_INDEX, _index_member(room_code, deadline_id)
            )
        except RedisError as exc:
            raise RoomStorageError("Deadline index is unavailable.") from exc

    async def rebuild_category_deadline_index(self) -> None:
        """Backfill votes persisted before the index existed after API startup.

        A concurrent room transition may make an added entry stale. Its
        deadline ID is checked by the coordinator before it can do anything.
        """

        try:
            async for raw_key in self._client.scan_iter(match="codemafia:v1:room:*"):
                room_code = raw_key.decode("ascii").removeprefix("codemafia:v1:room:")
                stored = await self.load_room(room_code)
                if stored is None:
                    continue
                deadline = _category_deadline_member(stored.state)
                if deadline is not None:
                    await self._client.zadd(_CATEGORY_DEADLINE_INDEX, {deadline[0]: deadline[1]})
        except RedisError as exc:
            raise RoomStorageError("Deadline index could not be rebuilt.") from exc
        except UnicodeError as exc:
            raise RoomStorageError("Stored room key is invalid.") from exc
