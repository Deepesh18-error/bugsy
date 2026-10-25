"""Shared deadline checks and the game's action-at-deadline policy.

This module decides whether an absolute server-time deadline is still open,
due, stale, or invalid for a requested phase. The phase-specific state changes
remain in ``transitions.py``. A room coordinator must serialize all operations
for one room and pass the server receipt time into the transition engine.

The round-result pause has no implicit timeout: the host's continuation command
starts a server-prepared next round, whose coding deadline must still be in the
future. This avoids inventing a result-screen duration in the rules layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from .models import DeadlineKind, GameDeadline


class DeadlineStatus(str, Enum):
    """Result of comparing a deadline with server time and optional context."""

    NO_DEADLINE = "no_deadline"
    STALE_ID = "stale_id"
    WRONG_KIND = "wrong_kind"
    OPEN = "open"
    DUE = "due"


@dataclass(frozen=True, slots=True)
class DeadlineEvaluation:
    """Read-only result of evaluating one deadline."""

    status: DeadlineStatus
    deadline: GameDeadline | None

    @property
    def is_due(self) -> bool:
        return self.status is DeadlineStatus.DUE

    @property
    def accepts_player_action(self) -> bool:
        """Actions are timely only strictly before the deadline."""

        return self.status in {DeadlineStatus.NO_DEADLINE, DeadlineStatus.OPEN}


def require_utc_time(now: datetime) -> None:
    """Reject naive or non-UTC timestamps used for authoritative decisions."""

    if now.tzinfo is None or now.utcoffset() != timedelta(0):
        raise ValueError("now must be timezone-aware and use UTC")


def evaluate_deadline(
    deadline: GameDeadline | None,
    now: datetime,
    *,
    expected_id: str | None = None,
    expected_kind: DeadlineKind | None = None,
) -> DeadlineEvaluation:
    """Classify a deadline using the exact-boundary rule ``now >= due_at``.

    A matching deadline is OPEN before its due time and DUE at or after it.
    ID and kind mismatches are reported before time comparison so a late stale
    callback cannot accidentally resolve a newer phase.
    """

    require_utc_time(now)
    if deadline is None:
        return DeadlineEvaluation(DeadlineStatus.NO_DEADLINE, None)
    if expected_id is not None and deadline.deadline_id != expected_id:
        return DeadlineEvaluation(DeadlineStatus.STALE_ID, deadline)
    if expected_kind is not None and deadline.kind is not expected_kind:
        return DeadlineEvaluation(DeadlineStatus.WRONG_KIND, deadline)
    status = DeadlineStatus.OPEN if now < deadline.due_at else DeadlineStatus.DUE
    return DeadlineEvaluation(status, deadline)


def action_is_before_deadline(deadline: GameDeadline | None, now: datetime) -> bool:
    """Return whether an action may be accepted under the deadline policy.

    A phase without a deadline is open. At exactly ``due_at``, the deadline
    wins and the player action is late.
    """

    evaluation = evaluate_deadline(deadline, now)
    return evaluation.status in {DeadlineStatus.NO_DEADLINE, DeadlineStatus.OPEN}
