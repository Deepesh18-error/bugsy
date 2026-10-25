"""Immutable player commands accepted as input to future game transitions.

A command records an attempted action; authorization, phase checks, deadlines,
and rule decisions belong to the transition functions. Collaborative source
edits travel through the room's Yjs document channel, not these commands.
Clients may request official testing, but only a trusted runner can produce an
official test result.
"""

from __future__ import annotations

from dataclasses import dataclass


def _require_non_blank(value: str, field_name: str, *, max_length: int) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    if len(value) > max_length:
        raise ValueError(f"{field_name} must be at most {max_length} characters")


@dataclass(frozen=True, slots=True, kw_only=True)
class GameCommand:
    """Shared metadata for a player-originated action.

    The API adapter must derive ``player_id`` from the authenticated connection;
    it must not trust a client-supplied identity field.
    """

    request_id: str
    player_id: str

    def __post_init__(self) -> None:
        _require_non_blank(self.request_id, "request_id", max_length=128)
        _require_non_blank(self.player_id, "player_id", max_length=128)


@dataclass(frozen=True, slots=True, kw_only=True)
class SetReady(GameCommand):
    """Set the caller's ready flag to the supplied value."""

    ready: bool

    def __post_init__(self) -> None:
        GameCommand.__post_init__(self)
        if not isinstance(self.ready, bool):
            raise ValueError("ready must be a boolean")


@dataclass(frozen=True, slots=True, kw_only=True)
class StartMatch(GameCommand):
    """Ask to start the match; the engine checks host and lobby requirements."""


@dataclass(frozen=True, slots=True, kw_only=True)
class StartNextRound(GameCommand):
    """Ask the host to start the server-selected next challenge after results."""


@dataclass(frozen=True, slots=True, kw_only=True)
class CastCategoryVote(GameCommand):
    """Choose one supported category during the category-vote phase."""

    category_id: str

    def __post_init__(self) -> None:
        GameCommand.__post_init__(self)
        _require_non_blank(self.category_id, "category_id", max_length=64)


@dataclass(frozen=True, slots=True, kw_only=True)
class CallEmergencyMeeting(GameCommand):
    """Request a meeting; eligibility and cooldown are transition rules."""


@dataclass(frozen=True, slots=True, kw_only=True)
class CastPlayerVote(GameCommand):
    """Vote for a player, or skip by setting target_player_id to None."""

    target_player_id: str | None

    def __post_init__(self) -> None:
        GameCommand.__post_init__(self)
        if self.target_player_id is not None:
            _require_non_blank(
                self.target_player_id,
                "target_player_id",
                max_length=128,
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class RequestOfficialTestRun(GameCommand):
    """Request a runner job for a known shared-source revision."""

    source_revision_id: str

    def __post_init__(self) -> None:
        GameCommand.__post_init__(self)
        _require_non_blank(
            self.source_revision_id,
            "source_revision_id",
            max_length=128,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class SendChatMessage(GameCommand):
    """Send bounded plain-text chat; rendering and rate limits are external."""

    message: str

    def __post_init__(self) -> None:
        GameCommand.__post_init__(self)
        _require_non_blank(self.message, "message", max_length=500)


@dataclass(frozen=True, slots=True, kw_only=True)
class LeaveRoom(GameCommand):
    """Leave the room; host transfer and departure rules run in the engine."""


@dataclass(frozen=True, slots=True, kw_only=True)
class EndRoom(GameCommand):
    """Ask to close the room; the engine checks that the caller is the host."""


@dataclass(frozen=True, slots=True, kw_only=True)
class RequestRematch(GameCommand):
    """Request a rematch after a finished game; acceptance policy is a rule."""


GameCommandType = (
    SetReady
    | StartMatch
    | StartNextRound
    | CastCategoryVote
    | CallEmergencyMeeting
    | CastPlayerVote
    | RequestOfficialTestRun
    | SendChatMessage
    | LeaveRoom
    | EndRoom
    | RequestRematch
)
