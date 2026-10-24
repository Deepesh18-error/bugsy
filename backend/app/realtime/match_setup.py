"""Trusted choices and deadlines for the lobby-to-role-reveal transition.

The game engine validates the choices. This module deliberately does not read
Redis, publish events, or expose the impostor choice to the browser.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

from app.challenges.loader import ChallengeLoadError, LoadedChallenge, load_challenge
from app.game.deadlines import require_utc_time
from app.game.models import (
    ConnectionStatus, DeadlineKind, GameDeadline, GamePhase, RoomState,
    RoundState, SabotageObjectiveProgress,
)
from app.game.randomness import ChoiceSource
from app.game.transitions import resolve_category_vote
from app.game.outcomes import TransitionOutcome


@dataclass(frozen=True, slots=True)
class MatchSetupPolicy:
    """Server-owned setup durations; both may be configured at composition time."""

    category_vote_seconds: int = 30
    role_reveal_seconds: int = 8
    coding_round_seconds: int = 180
    allow_draft_content: bool = True

    def __post_init__(self) -> None:
        if type(self.category_vote_seconds) is not int or self.category_vote_seconds <= 0:
            raise ValueError("Category voting duration must be a positive integer.")
        if type(self.role_reveal_seconds) is not int or self.role_reveal_seconds <= 0:
            raise ValueError("Role reveal duration must be a positive integer.")
        if type(self.coding_round_seconds) is not int or self.coding_round_seconds <= 0:
            raise ValueError("Coding-round duration must be a positive integer.")


# Only the Counter challenge exists today. The catalog is deliberately small
# until other categories have reviewed, version-pinned content.
PINNED_CHALLENGES = {"object-oriented": ("oop.counter", "1.0.0")}


def eligible_challenge(category_id: str, policy: MatchSetupPolicy) -> LoadedChallenge | None:
    identity = PINNED_CHALLENGES.get(category_id)
    if identity is None:
        return None
    try:
        loaded = load_challenge(*identity)
    except ChallengeLoadError:
        return None
    if loaded.challenge.category != category_id:
        return None
    if loaded.challenge.authorship.review_status == "draft" and not policy.allow_draft_content:
        return None
    return loaded


def available_categories(policy: MatchSetupPolicy) -> tuple[str, ...]:
    return tuple(category for category in PINNED_CHALLENGES if eligible_challenge(category, policy))


def make_phase_deadline(kind: DeadlineKind, now: datetime, seconds: int) -> GameDeadline:
    """Give each phase instance a new ID so old timeout callbacks are harmless."""

    require_utc_time(now)
    if type(seconds) is not int or seconds <= 0:
        raise ValueError("A phase duration must be a positive integer.")
    if kind not in {DeadlineKind.CATEGORY_VOTE, DeadlineKind.ROLE_REVEAL, DeadlineKind.CODING_ROUND}:
        raise ValueError("Match setup only creates category, reveal, and coding deadlines.")
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
    eligible = available_categories(policy)
    if not eligible:
        raise ValueError("No eligible challenge category is available.")
    counts = Counter(
        vote.target_id for vote in state.match.category_votes
        if vote.target_id in eligible
    )
    if counts:
        highest = max(counts.values())
        categories = tuple(sorted(category for category, count in counts.items() if count == highest and category in eligible))
    else:
        categories = eligible
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


def make_first_round(state: RoomState, now: datetime, policy: MatchSetupPolicy) -> RoundState:
    """Pin the first authored challenge after the private reveal deadline."""

    require_utc_time(now)
    match = state.match
    if match is None or match.match_id is None or match.selected_category_id is None:
        raise ValueError("A selected match is required to start a coding round.")
    loaded = eligible_challenge(match.selected_category_id, policy)
    if loaded is None:
        raise ValueError("The selected challenge is unavailable.")
    return RoundState(
        number=1,
        category_id=loaded.challenge.category,
        challenge_id=loaded.challenge.id,
        challenge_version=loaded.challenge.version,
        challenge_content_digest=loaded.content_digest,
        started_at=now,
        deadline=make_phase_deadline(DeadlineKind.CODING_ROUND, now, policy.coding_round_seconds),
        current_source_revision_id=f"seed-{uuid4().hex}",
        sabotage_objectives=tuple(
            SabotageObjectiveProgress(objective_id=item.id)
            for item in loaded.challenge.sabotage_objectives
        ),
    )
