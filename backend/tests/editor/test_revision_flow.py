"""Editor revision transitions and player-safe wire projections."""

import json
import unittest
from datetime import timedelta

from app.game.models import OfficialTestResult, PlayerRole
from app.game.outcomes import RejectionCode, TransitionAccepted, TransitionRejected
from app.game.transitions import record_source_revision
from app.realtime.snapshots import project_event, room_snapshot

from _support import NOW, coding_room


class RevisionFlowTests(unittest.TestCase):
    def test_revision_invalidates_old_test_result(self):
        prior = OfficialTestResult(
            run_id="run-a", source_revision_id="seed-a", completed_at=NOW,
            passed_test_ids=("test-a",), failed_test_ids=(), all_required_tests_passed=True,
        )
        room = coding_room(source_result=prior)
        outcome = record_source_revision(room, "rev-2", NOW + timedelta(seconds=1))
        self.assertIsInstance(outcome, TransitionAccepted)
        self.assertIsNone(outcome.state.match.current_round.official_test_result)
        self.assertEqual(outcome.state.match.current_round.current_source_revision_id, "rev-2")

    def test_restore_is_a_new_revision_with_public_metadata_only(self):
        room = coding_room()
        outcome = record_source_revision(
            room, "rev-restored", NOW + timedelta(seconds=1),
            restored_from_revision_id="rev-old", restored_by_player_id="p2",
        )
        self.assertIsInstance(outcome, TransitionAccepted)
        self.assertEqual([type(event).__name__ for event in outcome.events],
                         ["SourceRevisionChanged", "SourceRevisionRestored"])
        recipient, event = project_event(outcome.events[1], 7)
        self.assertIsNone(recipient)
        self.assertEqual(event.payload["restored_from_revision_id"], "rev-old")
        self.assertNotIn("source", event.payload)
        self.assertNotIn("impostor", json.dumps(event.model_dump()))

    def test_bad_restore_metadata_and_expired_round_are_rejected(self):
        room = coding_room()
        missing_actor = record_source_revision(
            room, "rev-2", NOW, restored_from_revision_id="rev-old")
        self.assertIsInstance(missing_actor, TransitionRejected)
        self.assertEqual(missing_actor.code, RejectionCode.INVALID_SELECTION)
        too_late = record_source_revision(room, "rev-2", NOW + timedelta(minutes=11))
        self.assertIsInstance(too_late, TransitionRejected)
        self.assertEqual(too_late.state, room)

    def test_snapshot_exposes_only_own_role_and_revision_pointer(self):
        room = coding_room()
        civilian = room_snapshot(room, "p1", 3).model_dump(mode="json")
        impostor = room_snapshot(room, "p4", 3).model_dump(mode="json")
        self.assertEqual(civilian["room"]["current_source_revision_id"], "seed-a")
        self.assertEqual(civilian["room"]["own_role"], PlayerRole.CIVILIAN.value)
        self.assertEqual(impostor["room"]["own_role"], PlayerRole.IMPOSTOR.value)
        self.assertNotIn("impostor", json.dumps(civilian))
        self.assertNotIn("source", json.dumps(civilian).replace("current_source_revision_id", ""))


if __name__ == "__main__":
    unittest.main()
