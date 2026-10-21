"""Immutable facts emitted by game-state transitions.

Events describe what has already happened; they do not request a change. They
are internal domain records, not ready-made WebSocket payloads. In particular,
private events must be routed only to their named recipient.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from .models import MatchEndReason, MatchWinner, PlayerRole


class GameEvent:
    """Base type for facts emitted by a transition."""

    occurred_at: datetime
    request_id: str | None


class PrivateGameEvent(GameEvent):
    """Marker base for events that must be delivered to one player only."""

    recipient_player_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class PlayerReadinessChanged(GameEvent):
    occurred_at: datetime
    request_id: str
    player_id: str
    is_ready: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class MatchStarted(GameEvent):
    occurred_at: datetime
    request_id: str
    room_code: str


@dataclass(frozen=True, slots=True, kw_only=True)
class CategoryVoteRecorded(GameEvent):
    """A category ballot; the protocol may choose to expose only its count."""

    occurred_at: datetime
    request_id: str
    player_id: str
    category_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class CategorySelected(GameEvent):
    occurred_at: datetime
    request_id: str | None
    category_id: str
    vote_counts: tuple[tuple[str, int], ...]
    used_fallback: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class PlayerRoleAssigned(PrivateGameEvent):
    """Private role reveal. Never broadcast to the whole room."""

    occurred_at: datetime
    request_id: str | None
    recipient_player_id: str
    role: PlayerRole


@dataclass(frozen=True, slots=True, kw_only=True)
class CodingRoundStarted(GameEvent):
    occurred_at: datetime
    request_id: str | None
    round_number: int
    category_id: str
    challenge_id: str
    challenge_version: str
    challenge_content_digest: str
    deadline_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class MeetingStarted(GameEvent):
    occurred_at: datetime
    request_id: str
    caller_player_id: str
    discussion_deadline_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class PlayerVotingStarted(GameEvent):
    occurred_at: datetime
    request_id: str | None
    deadline_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class PlayerBallotStored(PrivateGameEvent):
    """Acknowledges one player's ballot without exposing it to other players."""

    occurred_at: datetime
    request_id: str
    recipient_player_id: str
    is_skip: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class PlayerVoteResolved(GameEvent):
    """Public aggregate only; individual ballots are deliberately omitted."""

    occurred_at: datetime
    request_id: str | None
    vote_counts: tuple[tuple[str, int], ...]
    skip_count: int
    ejected_player_id: str | None
    was_tie: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class PlayerEliminated(GameEvent):
    occurred_at: datetime
    request_id: str | None
    player_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class OfficialTestRunRequested(GameEvent):
    occurred_at: datetime
    request_id: str
    player_id: str
    source_revision_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class OfficialTestResultAccepted(GameEvent):
    """Safe summary; hidden test IDs and failure details are not included."""

    occurred_at: datetime
    request_id: str | None
    source_revision_id: str
    all_required_tests_passed: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceRevisionChanged(GameEvent):
    occurred_at: datetime
    request_id: str | None
    source_revision_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class SabotageObjectiveVerified(PrivateGameEvent):
    """The impostor alone receives objective progress and its evidence revision."""

    occurred_at: datetime
    request_id: str | None
    recipient_player_id: str
    objective_id: str
    source_revision_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class RoundEnded(GameEvent):
    occurred_at: datetime
    request_id: str | None
    round_number: int


@dataclass(frozen=True, slots=True, kw_only=True)
class MatchEnded(GameEvent):
    occurred_at: datetime
    request_id: str | None
    winner: MatchWinner
    reason: MatchEndReason
    round_number: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ChatMessagePosted(GameEvent):
    occurred_at: datetime
    request_id: str
    player_id: str
    message: str


@dataclass(frozen=True, slots=True, kw_only=True)
class PlayerDeparted(GameEvent):
    occurred_at: datetime
    request_id: str | None
    player_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class PlayerDisconnected(GameEvent):
    occurred_at: datetime
    request_id: str | None
    player_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class PlayerReconnected(GameEvent):
    occurred_at: datetime
    request_id: str | None
    player_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class HostTransferred(GameEvent):
    occurred_at: datetime
    request_id: str | None
    previous_host_player_id: str
    new_host_player_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class RoomClosed(GameEvent):
    occurred_at: datetime
    request_id: str | None
    room_code: str


@dataclass(frozen=True, slots=True, kw_only=True)
class RematchRequested(GameEvent):
    occurred_at: datetime
    request_id: str
    player_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class RematchStarted(GameEvent):
    occurred_at: datetime
    request_id: str | None
    room_code: str
