"""Bounded request-ID deduplication for retry-safe game commands.

The in-memory store is suitable for the current single-process domain phase.
The later room coordinator must use a shared durable store (such as Redis) and
commit deduplication records atomically with room-state changes before running
multiple API workers.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import asdict, dataclass, is_dataclass
from hashlib import sha256
import json
import math
from datetime import datetime
from threading import Condition
from time import monotonic
from typing import Callable

from .commands import GameCommand, GameCommandType
from .models import GameDeadline, RoomState
from .outcomes import (
    RejectionCode,
    TransitionOutcome,
    TransitionRejected,
)


DEFAULT_REQUEST_ID_TTL_SECONDS = 10 * 60
DEFAULT_MAX_CACHED_REQUESTS = 10_000


@dataclass(frozen=True, slots=True)
class IdempotentExecution:
    """Transition result plus whether it came from the retry cache."""

    outcome: TransitionOutcome
    replayed: bool


@dataclass(frozen=True, slots=True)
class _CachedRequest:
    fingerprint: str
    expires_at: float
    outcome: TransitionOutcome


def _command_fingerprint(command: GameCommand) -> str:
    """Hash command type and payload so reused IDs cannot change meaning."""

    if not is_dataclass(command):
        raise TypeError("game commands must be dataclass instances")
    payload = {
        "type": f"{type(command).__module__}.{type(command).__qualname__}",
        "fields": asdict(command),
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


class RequestIdempotencyStore:
    """Remember one outcome per room/player/request ID for a bounded period.

    Policy: cache accepted and rejected outcomes for ten minutes by default,
    with a 10,000-entry cap. Under pressure, the oldest cached entry is evicted
    first, so capacity can shorten retention. Expiry uses a monotonic clock,
    independent of wall-clock adjustments. The caller may inject a monotonic
    timestamp for deterministic scenarios.

    Same-key concurrent calls wait for the first operation and replay its
    result. The transition callback runs outside the store lock so unrelated
    requests can proceed concurrently. A room coordinator still needs its own
    per-room serialization for state updates.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_REQUEST_ID_TTL_SECONDS,
        max_entries: int = DEFAULT_MAX_CACHED_REQUESTS,
    ) -> None:
        if not math.isfinite(ttl_seconds) or ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be a finite positive number")
        if not isinstance(max_entries, int) or isinstance(max_entries, bool) or max_entries < 1:
            raise ValueError("max_entries must be a positive integer")
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._entries: OrderedDict[tuple[str, str, str], _CachedRequest] = OrderedDict()
        self._in_flight: dict[tuple[str, str, str], str] = {}
        self._condition = Condition()

    @property
    def ttl_seconds(self) -> float:
        return self._ttl_seconds

    @property
    def max_entries(self) -> int:
        return self._max_entries

    def execute(
        self,
        state: RoomState,
        command: GameCommand,
        operation: Callable[[], TransitionOutcome],
        *,
        monotonic_now: float | None = None,
    ) -> IdempotentExecution:
        """Run once or replay the original result for a repeated request.

        The key is scoped to ``(room_code, player_id, request_id)``. Reusing
        that key with a different command payload returns DUPLICATE_REQUEST
        instead of applying a second, different action.
        """

        if not command.request_id.strip() or not command.player_id.strip():
            raise ValueError("command request_id and player_id must be non-empty")
        current_time = monotonic() if monotonic_now is None else monotonic_now
        if not math.isfinite(current_time):
            raise ValueError("monotonic_now must be finite")

        key = (state.room_code, command.player_id, command.request_id)
        fingerprint = _command_fingerprint(command)

        while True:
            with self._condition:
                self._purge_expired(current_time)
                cached = self._entries.get(key)
                if cached is not None:
                    if cached.fingerprint != fingerprint:
                        return IdempotentExecution(
                            outcome=self._duplicate_payload_rejection(state, command),
                            replayed=False,
                        )
                    return IdempotentExecution(outcome=cached.outcome, replayed=True)

                pending_fingerprint = self._in_flight.get(key)
                if pending_fingerprint is not None:
                    if pending_fingerprint != fingerprint:
                        return IdempotentExecution(
                            outcome=self._duplicate_payload_rejection(state, command),
                            replayed=False,
                        )
                    self._condition.wait()
                    # Refresh real time after waking; a supplied timestamp is
                    # intentionally stable for deterministic caller scenarios.
                    if monotonic_now is None:
                        current_time = monotonic()
                    continue

                self._in_flight[key] = fingerprint
                break

        try:
            outcome = operation()
        except BaseException:
            with self._condition:
                self._in_flight.pop(key, None)
                self._condition.notify_all()
            raise

        with self._condition:
            committed_at = monotonic() if monotonic_now is None else current_time
            self._purge_expired(committed_at)
            self._entries[key] = _CachedRequest(
                fingerprint=fingerprint,
                expires_at=committed_at + self._ttl_seconds,
                outcome=outcome,
            )
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
            self._in_flight.pop(key, None)
            self._condition.notify_all()
        return IdempotentExecution(outcome=outcome, replayed=False)

    def clear_room(self, room_code: str) -> None:
        """Forget cached requests for a room when its lifecycle is discarded."""

        with self._condition:
            for key in tuple(self._entries):
                if key[0] == room_code:
                    del self._entries[key]
            self._condition.notify_all()

    def _purge_expired(self, now: float) -> None:
        while self._entries:
            oldest_key = next(iter(self._entries))
            if self._entries[oldest_key].expires_at > now:
                break
            del self._entries[oldest_key]

    @staticmethod
    def _duplicate_payload_rejection(
        state: RoomState,
        command: GameCommand,
    ) -> TransitionRejected:
        return TransitionRejected(
            state=state,
            code=RejectionCode.DUPLICATE_REQUEST,
            message="This request ID was already used for a different command.",
            request_id=command.request_id,
        )


def apply_command_idempotently(
    store: RequestIdempotencyStore,
    state: RoomState,
    command: GameCommandType,
    now: datetime,
    *,
    next_deadline: GameDeadline | None = None,
    meeting_cooldown_until: datetime | None = None,
    monotonic_now: float | None = None,
) -> IdempotentExecution:
    """Apply a player command through the retry store and transition engine.

    A coordinator should inspect ``result.replayed``: replayed outcomes are
    responses to a retry and must not be committed as a new room-state update.
    """

    # Import locally so the store's keying and caching primitives remain usable
    # without importing the transition module until this convenience is called.
    from .transitions import apply_command

    return store.execute(
        state,
        command,
        lambda: apply_command(
            state,
            command,
            now,
            next_deadline=next_deadline,
            meeting_cooldown_until=meeting_cooldown_until,
        ),
        monotonic_now=monotonic_now,
    )
