"""Trusted editor/runner facts and objective victory in the pure engine."""

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import timedelta

from app.game.events import MatchEnded, PrivateGameEvent, SabotageObjectiveVerified
from app.game.models import (
    GamePhase,
    MatchEndReason,
    ObjectiveStatus,
    OfficialTestResult,
    SabotageObjectiveProgress,
)
from app.game.outcomes import RejectionCode, TransitionAccepted, TransitionRejected
from app.game.transitions import (
    end_coding_round,
    record_official_test_result,
    record_source_revision,
    record_verified_sabotage_objective,
)
from _builders import NOW, make_coding_room


class SabotageAndRevisionTests(unittest.TestCase):
    def test_edit_invalidates_failed_result_and_old_runner_result_cannot_win(self) -> None:
        original = make_coding_room()
        failed = OfficialTestResult(
            run_id="run-fail", source_revision_id="revision-1",
            completed_at=NOW + timedelta(seconds=1), all_required_tests_passed=False,
        )
        recorded = record_official_test_result(original, failed, NOW + timedelta(seconds=1))
        self.assertIsInstance(recorded, TransitionAccepted)
        edited = record_source_revision(recorded.state, "revision-2", NOW + timedelta(seconds=2))
        self.assertIsInstance(edited, TransitionAccepted)
        self.assertIsNone(edited.state.match.current_round.official_test_result)
        self.assertEqual(original.match.current_round.current_source_revision_id, "revision-1")

        old_pass = OfficialTestResult(
            run_id="run-old-pass", source_revision_id="revision-1",
            completed_at=NOW + timedelta(seconds=3), all_required_tests_passed=True,
        )
        stale = record_official_test_result(edited.state, old_pass, NOW + timedelta(seconds=3))
        self.assertIsInstance(stale, TransitionRejected)
        self.assertEqual(stale.code, RejectionCode.STALE_REVISION)
        self.assertIs(stale.state, edited.state)

    def test_objectives_require_current_revision_and_win_only_when_all_verified(self) -> None:
        room = make_coding_room()
        round_state = replace(
            room.match.current_round,
            sabotage_objectives=(
                SabotageObjectiveProgress(objective_id="break-decrement"),
                SabotageObjectiveProgress(objective_id="break-reset"),
            ),
        )
        room = replace(room, match=replace(room.match, current_round=round_state))
        old = record_verified_sabotage_objective(
            room, "break-decrement", "wrong-revision", NOW + timedelta(seconds=1)
        )
        self.assertIsInstance(old, TransitionRejected)
        self.assertEqual(old.code, RejectionCode.STALE_REVISION)

        first = record_verified_sabotage_objective(
            room, "break-decrement", "revision-1", NOW + timedelta(seconds=2)
        )
        self.assertIsInstance(first, TransitionAccepted)
        self.assertEqual(first.state.phase, GamePhase.CODING_ROUND)
        progress_event = first.events[0]
        self.assertIsInstance(progress_event, SabotageObjectiveVerified)
        self.assertIsInstance(progress_event, PrivateGameEvent)
        self.assertEqual(progress_event.recipient_player_id, "p4")
        repeated = record_verified_sabotage_objective(
            first.state, "break-decrement", "revision-1", NOW + timedelta(seconds=3)
        )
        self.assertIsInstance(repeated, TransitionAccepted)
        self.assertEqual(repeated.events, ())

        second = record_verified_sabotage_objective(
            first.state, "break-reset", "revision-1", NOW + timedelta(seconds=4)
        )
        self.assertIsInstance(second, TransitionAccepted)
        self.assertEqual(second.state.phase, GamePhase.CODING_ROUND)
        self.assertIsNone(second.state.match.result)
        self.assertEqual(second.state.match.sabotage_credits_used, 1)
        failed = OfficialTestResult("verified-run", "revision-1", NOW + timedelta(seconds=4),
                                    failed_test_ids=("decrement",))
        checked = record_official_test_result(second.state, failed, NOW + timedelta(seconds=4))
        due = checked.state.match.current_round.deadline.due_at
        ended = end_coding_round(checked.state, due, deadline_id="coding-1")
        self.assertEqual(ended.state.phase, GamePhase.GAME_OVER)
        self.assertEqual(ended.state.match.result.reason, MatchEndReason.SABOTAGE_OBJECTIVES_COMPLETED)
        self.assertTrue(any(isinstance(event, MatchEnded) for event in ended.events))

    def test_edit_clears_verification_and_cooldown_survives_restore(self):
        room = make_coding_room()
        current = replace(room.match.current_round, sabotage_objectives=(SabotageObjectiveProgress("target"),))
        room = replace(room, match=replace(room.match, current_round=current))
        verified = record_verified_sabotage_objective(room, "target", "revision-1", NOW)
        edited = record_source_revision(verified.state, "revision-2", NOW + timedelta(seconds=1))
        self.assertEqual(edited.state.match.current_round.sabotage_objectives[0].status, ObjectiveStatus.NOT_STARTED)
        self.assertEqual(edited.state.match.sabotage_credits_used, 1)
        denied = record_verified_sabotage_objective(edited.state, "target", "revision-2", NOW + timedelta(seconds=2))
        self.assertIsInstance(denied, TransitionRejected)
        due = edited.state.match.current_round.deadline.due_at
        ended = end_coding_round(edited.state, due, deadline_id="coding-1")
        self.assertEqual(ended.state.phase, GamePhase.ROUND_RESULT)

    def test_budget_and_response_window_are_enforced(self):
        room = make_coding_room()
        current = replace(room.match.current_round, sabotage_objectives=(SabotageObjectiveProgress("target"),))
        room = replace(room, match=replace(room.match, current_round=current))
        exhausted = replace(room, match=replace(room.match, sabotage_credits_used=3))
        self.assertIsInstance(record_verified_sabotage_objective(exhausted, "target", "revision-1", NOW), TransitionRejected)
        late = current.deadline.due_at - timedelta(seconds=29)
        self.assertIsInstance(record_verified_sabotage_objective(room, "target", "revision-1", late), TransitionRejected)
        boundary = current.deadline.due_at - timedelta(seconds=30)
        self.assertIsInstance(record_verified_sabotage_objective(room, "target", "revision-1", boundary), TransitionAccepted)

    def test_unknown_objective_and_verdict_at_deadline_are_rejected(self) -> None:
        room = make_coding_room()
        unknown = record_verified_sabotage_objective(room, "invented", "revision-1", NOW)
        self.assertIsInstance(unknown, TransitionRejected)
        self.assertEqual(unknown.code, RejectionCode.INVALID_OBJECTIVE)
        at_deadline = record_source_revision(
            room, "revision-2", room.match.current_round.deadline.due_at
        )
        self.assertIsInstance(at_deadline, TransitionRejected)
        self.assertEqual(at_deadline.code, RejectionCode.DEADLINE_PASSED)

    def test_two_serial_edits_only_allow_latest_revision_to_win(self) -> None:
        room = make_coding_room()
        first = record_source_revision(room, "revision-civilian", NOW + timedelta(seconds=1))
        self.assertIsInstance(first, TransitionAccepted)
        second = record_source_revision(
            first.state, "revision-impostor", NOW + timedelta(seconds=2)
        )
        self.assertIsInstance(second, TransitionAccepted)
        older_pass = OfficialTestResult(
            run_id="pass-first-edit", source_revision_id="revision-civilian",
            completed_at=NOW + timedelta(seconds=3), all_required_tests_passed=True,
        )
        stale = record_official_test_result(second.state, older_pass, NOW + timedelta(seconds=3))
        self.assertIsInstance(stale, TransitionRejected)
        self.assertEqual(stale.code, RejectionCode.STALE_REVISION)
        self.assertEqual(second.state.match.current_round.current_source_revision_id, "revision-impostor")


if __name__ == "__main__":
    unittest.main()
