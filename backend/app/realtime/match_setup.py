"""Trusted choices and deadlines for the lobby-to-role-reveal transition.

The game engine validates the choices. This module deliberately does not read
Redis, publish events, or expose the impostor choice to the browser.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

from app.game.deadlines import require_utc_time
from app.game.models import ConnectionStatus, DeadlineKind, GameDeadline, GamePhase, RoomState
from app.game.randomness import ChoiceSource
from app.game.transitions import SUPPORTED_CATEGORY_IDS, resolve_category_vote
from app.game.outcomes import TransitionOutcome


@dataclass(frozen=True, slots=True)
class MatchSetupPolicy:
    """Server-owned setup durations; both may be configured at composition time."""

    category_vote_seconds: int = 30
    role_reveal_seconds: int = 8

    def __post_init__(self) -> None:
        if type(self.category_vote_seconds) is not int or self.category_vote_seconds <= 0:
            raise ValueError("Category voting duration must be a positive integer.")
        if type(self.role_reveal_seconds) is not int or self.role_reveal_seconds <= 0:
            raise ValueError("Role reveal duration must be a positive integer.")


def make_phase_deadline(kind: DeadlineKind, now: datetime, seconds: int) -> GameDeadline:
    """Give each phase instance a new ID so old timeout callbacks are harmless."""

    require_utc_time(now)
    if type(seconds) is not int or seconds <= 0:
        raise ValueError("A phase duration must be a positive integer.")
    if kind not in {DeadlineKind.CATEGORY_VOTE, DeadlineKind.ROLE_REVEAL}:
        raise ValueError("Match setup only creates category and role-reveal deadlines.")
    return GameDeadline(
        deadline_id=uuid4().hex,
        kind=kind,
        due_at=now + timedelta(seconds=seconds),
    )


def category_vote_is_complete(state: RoomState) -> bool:
    """Resolve early only after each connected, living player has voted."""

    if state.phase is not GamePhase.CATEGORY_VOTE or state.match is None:
        return False
    eligible = tuple(
        player.player_id for player in state.players
        if player.connection is ConnectionStatus.CONNECTED and player.is_alive
    )
    ballots = {vote.voter_id for vote in state.match.category_votes}
    return bool(eligible) and all(player_id in ballots for player_id in eligible)


def resolve_match_setup(
    state: RoomState,
    now: datetime,
    *,
    choices: ChoiceSource,
    policy: MatchSetupPolicy,
) -> TransitionOutcome:
    """Choose a winning category and one impostor, then ask the engine to commit.

    Candidate ordering is stable for scripted replay. Live callers use a
    SecureChoiceSource; no room-code hash or browser choice assigns roles.
    """

    require_utc_time(now)
    if state.phase is not GamePhase.CATEGORY_VOTE or state.match is None:
        raise ValueError("Match setup requires an open category ballot.")
    counts = Counter(
        vote.target_id for vote in state.match.category_votes
        if vote.target_id is not None
    )
    if counts:
        highest = max(counts.values())
        categories = tuple(sorted(category for category, count in counts.items() if count == highest))
    else:
        categories = SUPPORTED_CATEGORY_IDS
    participants = tuple(sorted(
        player.player_id for player in state.players
        if player.connection is not ConnectionStatus.DEPARTED
    ))
    # A malformed/closed room is rejected by the engine. Avoid choosing from
    # an empty collection before its validation can run.
    if not participants:
        raise ValueError("A match requires an active participant.")
    return resolve_category_vote(
        state,
        now,
        selected_category_id=choices.choose_one(categories),
        impostor_player_id=choices.choose_one(participants),
        role_reveal_deadline=make_phase_deadline(
            DeadlineKind.ROLE_REVEAL, now, policy.role_reveal_seconds
        ),
    )
