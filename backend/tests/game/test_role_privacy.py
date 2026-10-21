"""Guardrails for private role, ballot, and test-result information."""

from dataclasses import replace
from datetime import timedelta
import unittest

from app.game.commands import CastPlayerVote
from app.game.events import (
    OfficialTestResultAccepted,
    PlayerBallotStored,
    PlayerRoleAssigned,
    PrivateGameEvent,
)
from app.game.models import (
    DeadlineKind,
    GamePhase,
    GameDeadline,
    MatchState,
    OfficialTestResult,
    PlayerRole,
)
from app.game.outcomes import TransitionAccepted
from app.game.transitions import (
    apply_command,
    record_official_test_result,
    resolve_category_vote,
)

from _builders import NOW, make_coding_room, make_voting_room, make_lobby


class RolePrivacyTests(unittest.TestCase):
    def test_role_assignment_events_are_private_and_recipient_scoped(self) -> None:
        category_deadline = GameDeadline(
            deadline_id="category-privacy",
            kind=DeadlineKind.CATEGORY_VOTE,
            due_at=NOW,
        )
        base = make_lobby(deadline=category_deadline)
        category_state = replace(
            base,
            phase=GamePhase.CATEGORY_VOTE,
            match=MatchState(),
        )
        role_deadline = GameDeadline(
            deadline_id="role-reveal",
            kind=DeadlineKind.ROLE_REVEAL,
            due_at=NOW + timedelta(seconds=10),
        )

        result = resolve_category_vote(
            category_state,
            NOW,
            selected_category_id="object-oriented",
            impostor_player_id="p4",
            role_reveal_deadline=role_deadline,
        )

        self.assertIsInstance(result, TransitionAccepted)
        role_events = [event for event in result.events if isinstance(event, PlayerRoleAssigned)]
        self.assertEqual(len(role_events), 4)
        self.assertTrue(all(isinstance(event, PrivateGameEvent) for event in role_events))
        self.assertEqual(
            {event.recipient_player_id for event in role_events}, {"p1", "p2", "p3", "p4"}
        )
        self.assertEqual(
            [event.recipient_player_id for event in role_events if event.role is PlayerRole.IMPOSTOR],
            ["p4"],
        )
        self.assertTrue(
            all(not hasattr(event, "role") for event in result.events if not isinstance(event, PrivateGameEvent))
        )

    def test_ballot_acknowledgement_is_private_and_omits_target(self) -> None:
        result = apply_command(
            make_voting_room(),
            CastPlayerVote(request_id="private-vote", player_id="p1", target_player_id="p4"),
            NOW,
        )

        self.assertIsInstance(result, TransitionAccepted)
        event = result.events[0]
        self.assertIsInstance(event, PlayerBallotStored)
        self.assertEqual(event.recipient_player_id, "p1")
        self.assertFalse(event.is_skip)
        self.assertFalse(hasattr(event, "target_id"))
        self.assertFalse(hasattr(event, "target_player_id"))

    def test_public_test_result_event_contains_only_safe_summary(self) -> None:
        state = make_coding_room()
        result = OfficialTestResult(
            run_id="hidden-run",
            source_revision_id="revision-1",
            completed_at=NOW + timedelta(seconds=1),
            passed_test_ids=("public-a",),
            failed_test_ids=("secret-hidden-test",),
            all_required_tests_passed=False,
        )

        outcome = record_official_test_result(state, result, NOW + timedelta(seconds=2))

        self.assertIsInstance(outcome, TransitionAccepted)
        event = next(
            item for item in outcome.events if isinstance(item, OfficialTestResultAccepted)
        )
        self.assertFalse(hasattr(event, "passed_test_ids"))
        self.assertFalse(hasattr(event, "failed_test_ids"))
        self.assertFalse(hasattr(event, "run_id"))
        self.assertEqual(event.source_revision_id, "revision-1")
        self.assertFalse(event.all_required_tests_passed)


if __name__ == "__main__":
    unittest.main()
