"""Currently implemented civilian and impostor match-ending rules."""

from datetime import timedelta
import unittest

from app.game.commands import CastPlayerVote, FinalizeSolution
from app.game.events import MatchEnded
from app.game.models import (
    GamePhase,
    MatchEndReason,
    MatchWinner,
    OfficialTestResult,
)
from app.game.outcomes import RejectionCode, TransitionAccepted, TransitionRejected
from app.game.transitions import (
    apply_command,
    process_deadline,
    record_official_test_result,
    record_source_revision,
)

from _builders import NOW, make_coding_room, make_voting_room


class WinConditionTests(unittest.TestCase):
    def test_current_green_result_requires_explicit_finalization(self) -> None:
        state = make_coding_room()
        result = OfficialTestResult(
            run_id="run-1",
            source_revision_id="revision-1",
            completed_at=NOW + timedelta(seconds=5),
            passed_test_ids=("increment", "decrement", "reset"),
            all_required_tests_passed=True,
        )

        outcome = record_official_test_result(state, result, NOW + timedelta(seconds=6))

        self.assertIsInstance(outcome, TransitionAccepted)
        self.assertEqual(outcome.state.phase, GamePhase.CODING_ROUND)
        self.assertIsNone(outcome.state.match.result)
        self.assertFalse(any(isinstance(event, MatchEnded) for event in outcome.events))
        finalized = apply_command(
            outcome.state,
            FinalizeSolution(request_id="finalize-1", player_id="p1", source_revision_id="revision-1"),
            NOW + timedelta(seconds=7),
        )
        self.assertIsInstance(finalized, TransitionAccepted)
        self.assertEqual(finalized.state.phase, GamePhase.GAME_OVER)
        self.assertEqual(finalized.state.match.result.winner, MatchWinner.CIVILIANS)
        self.assertEqual(
            finalized.state.match.result.reason,
            MatchEndReason.REQUIRED_TESTS_PASSED,
        )
        self.assertTrue(any(isinstance(event, MatchEnded) for event in finalized.events))

    def test_edit_revokes_green_candidate_before_finalization(self) -> None:
        state = make_coding_room()
        result = OfficialTestResult(
            run_id="green-run", source_revision_id="revision-1",
            completed_at=NOW + timedelta(seconds=1),
            passed_test_ids=("increment", "decrement", "reset"),
            all_required_tests_passed=True,
        )
        green = record_official_test_result(state, result, NOW + timedelta(seconds=2))
        edited = record_source_revision(green.state, "revision-2", NOW + timedelta(seconds=3))
        self.assertIsNone(edited.state.match.current_round.official_test_result)
        rejected = apply_command(
            edited.state,
            FinalizeSolution(request_id="old-green", player_id="p1", source_revision_id="revision-1"),
            NOW + timedelta(seconds=4),
        )
        self.assertIsInstance(rejected, TransitionRejected)
        self.assertEqual(rejected.code, RejectionCode.STALE_REVISION)

    def test_finalization_at_deadline_is_rejected(self) -> None:
        due = NOW + timedelta(seconds=10)
        state = make_coding_room(due_at=due)
        result = OfficialTestResult(
            run_id="green-before-deadline", source_revision_id="revision-1",
            completed_at=NOW + timedelta(seconds=8),
            passed_test_ids=("increment", "decrement", "reset"),
            all_required_tests_passed=True,
        )
        green = record_official_test_result(state, result, NOW + timedelta(seconds=9))
        rejected = apply_command(
            green.state,
            FinalizeSolution(request_id="too-late", player_id="p1", source_revision_id="revision-1"),
            due,
        )
        self.assertIsInstance(rejected, TransitionRejected)
        self.assertEqual(rejected.code, RejectionCode.DEADLINE_PASSED)

    def test_stale_revision_test_result_cannot_win(self) -> None:
        state = make_coding_room()
        stale_result = OfficialTestResult(
            run_id="run-stale",
            source_revision_id="revision-before-edit",
            completed_at=NOW + timedelta(seconds=5),
            all_required_tests_passed=True,
        )

        outcome = record_official_test_result(
            state, stale_result, NOW + timedelta(seconds=6)
        )

        self.assertIsInstance(outcome, TransitionRejected)
        self.assertEqual(outcome.code, RejectionCode.STALE_REVISION)
        self.assertEqual(outcome.state.phase, GamePhase.CODING_ROUND)

    def test_surviving_round_four_deadline_wins_for_impostor(self) -> None:
        due = NOW + timedelta(seconds=10)
        state = make_coding_room(round_number=4, due_at=due)

        outcome = process_deadline(state, "coding-4", due)

        self.assertIsInstance(outcome, TransitionAccepted)
        self.assertEqual(outcome.state.phase, GamePhase.GAME_OVER)
        self.assertEqual(outcome.state.match.result.winner, MatchWinner.IMPOSTOR)
        self.assertEqual(
            outcome.state.match.result.reason,
            MatchEndReason.FINAL_DEADLINE_SURVIVED,
        )

    def test_ejecting_impostor_commits_civilian_win_before_later_round_timeout(self) -> None:
        state = make_voting_room()
        ballots = (("p1", "p4"), ("p2", "p4"), ("p3", "p4"), ("p4", "p1"))
        for index, (voter, target) in enumerate(ballots):
            outcome = apply_command(
                state,
                CastPlayerVote(
                    request_id=f"eject-{index}",
                    player_id=voter,
                    target_player_id=target,
                ),
                NOW + timedelta(seconds=index),
            )
            self.assertIsInstance(outcome, TransitionAccepted)
            state = outcome.state

        self.assertEqual(state.phase, GamePhase.GAME_OVER)
        self.assertEqual(state.match.result.winner, MatchWinner.CIVILIANS)
        self.assertEqual(state.match.result.reason, MatchEndReason.IMPOSTOR_EJECTED)
        stale_timeout = process_deadline(
            state,
            "coding-1",
            NOW + timedelta(minutes=5),
        )
        self.assertIsInstance(stale_timeout, TransitionRejected)
        self.assertEqual(stale_timeout.code, RejectionCode.STALE_DEADLINE)


if __name__ == "__main__":
    unittest.main()
