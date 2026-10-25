"""Multi-step scenarios combining the implemented game rules."""

from dataclasses import replace
from datetime import timedelta
import unittest

from app.game.commands import CastPlayerVote, FinalizeSolution, RequestOfficialTestRun
from app.game.models import (
    ConnectionStatus,
    GamePhase,
    OfficialTestResult,
    PlayerRole,
)
from app.game.outcomes import RejectionCode, TransitionAccepted, TransitionRejected
from app.game.transitions import (
    apply_command,
    process_deadline,
    record_official_test_result,
)

from _builders import NOW, make_coding_room, make_players, make_voting_room


class MatchScenarioTests(unittest.TestCase):
    def test_disconnected_player_is_not_required_to_vote_and_abstains(self) -> None:
        players = make_players(
            disconnected=frozenset({"p4"}),
            roles=(
                PlayerRole.CIVILIAN,
                PlayerRole.CIVILIAN,
                PlayerRole.IMPOSTOR,
                PlayerRole.CIVILIAN,
            ),
        )
        state = make_voting_room(players=players)
        ballots = (("p1", "p3"), ("p2", "p3"), ("p3", "p1"))

        for index, (voter, target) in enumerate(ballots):
            outcome = apply_command(
                state,
                CastPlayerVote(
                    request_id=f"disconnect-vote-{index}",
                    player_id=voter,
                    target_player_id=target,
                ),
                NOW + timedelta(seconds=index),
            )
            self.assertIsInstance(outcome, TransitionAccepted)
            state = outcome.state

        self.assertEqual(state.phase, GamePhase.GAME_OVER)
        self.assertEqual(state.match.result.reason.value, "impostor_ejected")
        disconnected = next(player for player in state.players if player.player_id == "p4")
        self.assertIs(disconnected.connection, ConnectionStatus.DISCONNECTED)

    def test_test_failure_does_not_end_match_and_later_pass_can_win(self) -> None:
        state = make_coding_room()
        failure = apply_command(
            state,
            RequestOfficialTestRun(
                request_id="request-fail", player_id="p1", source_revision_id="revision-1"
            ),
            NOW,
        )
        self.assertIsInstance(failure, TransitionAccepted)
        self.assertEqual(failure.state.phase, GamePhase.CODING_ROUND)

        failed_result = OfficialTestResult(
            run_id="failed-run",
            source_revision_id="revision-1",
            completed_at=NOW + timedelta(seconds=1),
            failed_test_ids=("decrement",),
            all_required_tests_passed=False,
        )
        after_failure = record_official_test_result(
            failure.state, failed_result, NOW + timedelta(seconds=2)
        )
        self.assertIsInstance(after_failure, TransitionAccepted)
        self.assertEqual(after_failure.state.phase, GamePhase.CODING_ROUND)

        passing_result = replace(
            failed_result,
            run_id="passing-run",
            completed_at=NOW + timedelta(seconds=3),
            passed_test_ids=("increment", "decrement", "reset"),
            failed_test_ids=(),
            all_required_tests_passed=True,
        )
        final = record_official_test_result(
            after_failure.state, passing_result, NOW + timedelta(seconds=4)
        )
        self.assertIsInstance(final, TransitionAccepted)
        self.assertEqual(final.state.phase, GamePhase.CODING_ROUND)
        claimed = apply_command(
            final.state,
            FinalizeSolution(request_id="claim-win", player_id="p1", source_revision_id="revision-1"),
            NOW + timedelta(seconds=5),
        )
        self.assertIsInstance(claimed, TransitionAccepted)
        self.assertEqual(claimed.state.phase, GamePhase.GAME_OVER)

    def test_code_revision_change_makes_previous_pass_result_stale(self) -> None:
        state = make_coding_room()
        previous_round = state.match.current_round
        edited_round = replace(
            previous_round,
            current_source_revision_id="revision-after-edit",
        )
        edited_match = replace(state.match, current_round=edited_round)
        edited_state = replace(state, match=edited_match)
        old_passing_result = OfficialTestResult(
            run_id="old-revision-pass",
            source_revision_id="revision-1",
            completed_at=NOW + timedelta(seconds=1),
            passed_test_ids=("increment", "decrement", "reset"),
            all_required_tests_passed=True,
        )

        outcome = record_official_test_result(
            edited_state,
            old_passing_result,
            NOW + timedelta(seconds=2),
        )

        self.assertIsInstance(outcome, TransitionRejected)
        self.assertEqual(outcome.code, RejectionCode.STALE_REVISION)
        self.assertEqual(outcome.state.phase, GamePhase.CODING_ROUND)

    def test_action_at_deadline_is_rejected_then_timeout_advances_phase(self) -> None:
        due = NOW + timedelta(seconds=20)
        state = make_coding_room(due_at=due)
        request = RequestOfficialTestRun(
            request_id="run-at-deadline", player_id="p1", source_revision_id="revision-1"
        )

        action_result = apply_command(state, request, due)
        deadline_result = process_deadline(state, "coding-1", due)

        self.assertIsInstance(action_result, TransitionRejected)
        self.assertEqual(action_result.code, RejectionCode.DEADLINE_PASSED)
        self.assertIsInstance(deadline_result, TransitionAccepted)
        self.assertEqual(deadline_result.state.phase, GamePhase.ROUND_RESULT)


if __name__ == "__main__":
    unittest.main()
