"""Typed accepted and rejected results from applying game rules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias

from .events import GameEvent
from .models import RoomState


class RejectionCode(str, Enum):
    """Stable machine-readable reasons an attempted action can be rejected."""

    ROOM_CLOSED = "room_closed"
    WRONG_PHASE = "wrong_phase"
    DEADLINE_PASSED = "deadline_passed"
    DEADLINE_NOT_REACHED = "deadline_not_reached"
    STALE_DEADLINE = "stale_deadline"
    PLAYER_NOT_FOUND = "player_not_found"
    PLAYER_NOT_CONNECTED = "player_not_connected"
    PLAYER_NOT_ELIGIBLE = "player_not_eligible"
    NOT_HOST = "not_host"
    NOT_READY = "not_ready"
    INVALID_PLAYER_COUNT = "invalid_player_count"
    INVALID_CATEGORY = "invalid_category"
    ALREADY_VOTED = "already_voted"
    INVALID_VOTE_TARGET = "invalid_vote_target"
    MEETING_ALREADY_USED = "meeting_already_used"
    MEETING_COOLDOWN = "meeting_cooldown"
    MISSING_DEADLINE = "missing_deadline"
    INVALID_DEADLINE = "invalid_deadline"
    INVALID_SELECTION = "invalid_selection"
    VOTE_NOT_COMPLETE = "vote_not_complete"
    STALE_REVISION = "stale_revision"
    RESULT_FROM_FUTURE = "result_from_future"
    MATCH_NOT_FINISHED = "match_not_finished"
    DUPLICATE_REQUEST = "duplicate_request"
    ACTION_NOT_SUPPORTED = "action_not_supported"


@dataclass(frozen=True, slots=True)
class TransitionAccepted:
    """The action was accepted, with the resulting immutable state and facts."""

    state: RoomState
    events: tuple[GameEvent, ...] = ()


@dataclass(frozen=True, slots=True)
class TransitionRejected:
    """The action was rejected; state is the original unchanged room state."""

    state: RoomState
    code: RejectionCode
    message: str
    request_id: str | None = None


TransitionOutcome: TypeAlias = TransitionAccepted | TransitionRejected
