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
    meeting_discussion_seconds: int = 30
    player_vote_seconds: int = 30
    meeting_cooldown_seconds: int = 60
    allow_draft_content: bool = True

    def __post_init__(self) -> None:
        if type(self.category_vote_seconds) is not int or self.category_vote_seconds <= 0:
            raise ValueError("Category voting duration must be a positive integer.")
        if type(self.role_reveal_seconds) is not int or self.role_reveal_seconds <= 0:
            raise ValueError("Role reveal duration must be a positive integer.")
        if type(self.coding_round_seconds) is not int or self.coding_round_seconds <= 0:
            raise ValueError("Coding-round duration must be a positive integer.")
        if type(self.meeting_discussion_seconds) is not int or self.meeting_discussion_seconds <= 0:
            raise ValueError("Meeting discussion duration must be a positive integer.")
        if type(self.player_vote_seconds) is not int or self.player_vote_seconds <= 0:
            raise ValueError("Player-vote duration must be a positive integer.")
        if type(self.meeting_cooldown_seconds) is not int or self.meeting_cooldown_seconds <= 0:
            raise ValueError("Meeting cooldown duration must be a positive integer.")


# Explicit content pins; draft versions remain staging/development-only.
PINNED_CHALLENGES = {
    "object-oriented": (("oop.counter", "1.1.0"), ("oop.stack", "1.0.0")),
    "back-end": (("backend.wallet", "1.0.0"),),
    "c-plus-plus": (("cpp.score", "1.0.0"),),
}


def eligible_challenges(category_id: str, policy: MatchSetupPolicy) -> tuple[LoadedChallenge, ...]:
    candidates = []
    for identity in PINNED_CHALLENGES.get(category_id, ()):
        try:
            loaded = load_challenge(*identity)
        except ChallengeLoadError:
            continue
        if loaded.challenge.category != category_id:
            continue
        if loaded.challenge.authorship.review_status == "draft" and not policy.allow_draft_content:
            continue
        candidates.append(loaded)
    return tuple(candidates)


def eligible_challenge(category_id: str, policy: MatchSetupPolicy) -> LoadedChallenge | None:
    candidates = eligible_challenges(category_id, policy)
    return candidates[0] if candidates else None


def available_categories(policy: MatchSetupPolicy) -> tuple[str, ...]:
    return tuple(category for category in PINNED_CHALLENGES if eligible_challenge(category, policy))


def make_phase_deadline(kind: DeadlineKind, now: datetime, seconds: int) -> GameDeadline:
    """Give each phase instance a new ID so old timeout callbacks are harmless."""

    require_utc_time(now)
    if type(seconds) is not int or seconds <= 0:
        raise ValueError("A phase duration must be a positive integer.")
    if kind not in {
        DeadlineKind.CATEGORY_VOTE,
        DeadlineKind.ROLE_REVEAL,
        DeadlineKind.CODING_ROUND,
        DeadlineKind.MEETING_DISCUSSION,
        DeadlineKind.PLAYER_VOTE,
    }:
        raise ValueError("Unsupported timed game phase.")
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


def make_next_round(
    state: RoomState,
    now: datetime,
    policy: MatchSetupPolicy,
    *,
    choices: ChoiceSource,
) -> RoundState:
    """Build a fresh, server-selected round in the match's pinned category.

    Prefer an unused challenge when the authored bank has one. Until more
    content is authored, reuse the eligible challenge so a four-round match
    remains playable; every round still receives a new document/revision ID.
    """

    require_utc_time(now)
    match = state.match
    current = match.current_round if match is not None else None
    if (
        state.phase is not GamePhase.ROUND_RESULT
        or match is None
        or match.match_id is None
        or match.selected_category_id is None
        or current is None
    ):
        raise ValueError("A completed coding round is required to prepare the next round.")
    category_id = match.selected_category_id
    candidates = eligible_challenges(category_id, policy)
    if not candidates:
        raise ValueError("No eligible challenge is available for the selected category.")
    used = {
        (item.challenge_id, item.challenge_version)
        for item in (*match.round_history, current)
    }
    fresh = tuple(
        item for item in candidates
        if (item.challenge.id, item.challenge.version) not in used
    )
    selected = choices.choose_one(fresh or tuple(candidates))
    number = match.round_number + 1
    return RoundState(
        number=number,
        category_id=selected.challenge.category,
        challenge_id=selected.challenge.id,
        challenge_version=selected.challenge.version,
        challenge_content_digest=selected.content_digest,
        started_at=now,
        deadline=make_phase_deadline(
            DeadlineKind.CODING_ROUND, now, policy.coding_round_seconds
        ),
        current_source_revision_id=f"seed-{uuid4().hex}",
        sabotage_objectives=tuple(
            SabotageObjectiveProgress(objective_id=item.id)
            for item in selected.challenge.sabotage_objectives
        ),
    )
