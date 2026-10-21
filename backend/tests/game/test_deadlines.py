"""Deadline boundary, stale callback, and phase-expiry behavior."""

from dataclasses import replace
from datetime import timedelta
import unittest

from app.game.commands import CallEmergencyMeeting, RequestOfficialTestRun, SetReady
from app.game.deadlines import DeadlineStatus, action_is_before_deadline, evaluate_deadline
from app.game.events import RoundEnded
from app.game.models import DeadlineKind, GamePhase
from app.game.outcomes import RejectionCode, TransitionAccepted, TransitionRejected
from app.game.transitions import apply_command, process_deadline

from _builders import NOW, make_coding_room, make_deadline, make_discussion_room, make_lobby


class DeadlineTests(unittest.TestCase):
    def test_deadline_is_open_before_due_and_due_at_exact_boundary(self) -> None:
        deadline = make_deadline(
            "coding-1", DeadlineKind.CODING_ROUND, NOW + timedelta(seconds=10)
        )

        self.assertEqual(evaluate_deadline(deadline, NOW).status, DeadlineStatus.OPEN)
        self.assertTrue(action_is_before_deadline(deadline, NOW + timedelta(seconds=9)))
        self.assertEqual(
            evaluate_deadline(deadline, NOW + timedelta(seconds=10)).status,
            DeadlineStatus.DUE,
        )
        self.assertFalse(action_is_before_deadline(deadline, deadline.due_at))

    def test_lobby_action_at_exact_deadline_is_rejected(self) -> None:
        deadline = make_deadline(
            "room-lobby", DeadlineKind.ROOM_EXPIRY, NOW + timedelta(seconds=10)
        )
        state = make_lobby(deadline=deadline)

        result = apply_command(
            state,
            SetReady(request_id="late-ready", player_id="p1", ready=True),
            deadline.due_at,
        )

        self.assertIsInstance(result, TransitionRejected)
        self.assertEqual(result.code, RejectionCode.DEADLINE_PASSED)

    def test_coding_deadline_rejects_early_then_ends_round_when_due(self) -> None:
        due = NOW + timedelta(seconds=10)
        state = make_coding_room(due_at=due)

        early = process_deadline(state, "coding-1", due - timedelta(microseconds=1))
        self.assertIsInstance(early, TransitionRejected)
        self.assertEqual(early.code, RejectionCode.DEADLINE_NOT_REACHED)

        ended = process_deadline(state, "coding-1", due)
        self.assertIsInstance(ended, TransitionAccepted)
        self.assertEqual(ended.state.phase, GamePhase.ROUND_RESULT)
        self.assertTrue(any(isinstance(event, RoundEnded) for event in ended.events))

    def test_repeated_or_old_deadline_callback_cannot_end_new_phase(self) -> None:
        due = NOW + timedelta(seconds=10)
        state = make_coding_room(due_at=due)
        ended = process_deadline(state, "coding-1", due)

        repeated = process_deadline(ended.state, "coding-1", due + timedelta(seconds=1))
        wrong_id = process_deadline(state, "older-coding-0", due)

        self.assertIsInstance(repeated, TransitionRejected)
        self.assertEqual(repeated.code, RejectionCode.STALE_DEADLINE)
        self.assertIsInstance(wrong_id, TransitionRejected)
        self.assertEqual(wrong_id.code, RejectionCode.STALE_DEADLINE)

    def test_discussion_deadline_starts_player_vote_with_new_deadline(self) -> None:
        state = make_discussion_room()
        discussion = state.phase_deadline
        vote_deadline = make_deadline(
            "vote-after-discussion",
            DeadlineKind.PLAYER_VOTE,
            discussion.due_at + timedelta(seconds=20),
        )

        result = process_deadline(
            state,
            discussion.deadline_id,
            discussion.due_at,
            next_deadline=vote_deadline,
        )

        self.assertIsInstance(result, TransitionAccepted)
        self.assertEqual(result.state.phase, GamePhase.PLAYER_VOTE)
        self.assertEqual(result.state.phase_deadline, vote_deadline)

    def test_meeting_pauses_and_records_the_coding_deadline(self) -> None:
        coding_deadline = NOW + timedelta(seconds=60)
        state = make_coding_room(due_at=coding_deadline)
        discussion_deadline = make_deadline(
            "discussion-from-meeting",
            DeadlineKind.MEETING_DISCUSSION,
            NOW + timedelta(seconds=15),
        )
        cooldown_until = NOW + timedelta(seconds=45)

        result = apply_command(
            state,
            CallEmergencyMeeting(request_id="meeting-1", player_id="p2"),
            NOW,
            next_deadline=discussion_deadline,
            meeting_cooldown_until=cooldown_until,
        )

        self.assertIsInstance(result, TransitionAccepted)
        self.assertEqual(result.state.phase, GamePhase.MEETING_DISCUSSION)
        self.assertEqual(result.state.phase_deadline, discussion_deadline)
        self.assertEqual(result.state.match.paused_round_deadline.due_at, coding_deadline)
        self.assertEqual(result.state.match.meeting_cooldown_until, cooldown_until)
        caller = next(player for player in result.state.players if player.player_id == "p2")
        self.assertEqual(caller.emergency_meetings_used, 1)

    def test_meeting_cannot_be_called_at_the_coding_deadline(self) -> None:
        due = NOW + timedelta(seconds=10)
        state = make_coding_room(due_at=due)
        result = apply_command(
            state,
            CallEmergencyMeeting(request_id="meeting-late", player_id="p2"),
            due,
            next_deadline=make_deadline(
                "late-discussion",
                DeadlineKind.MEETING_DISCUSSION,
                due + timedelta(seconds=10),
            ),
            meeting_cooldown_until=due + timedelta(seconds=20),
        )

        self.assertIsInstance(result, TransitionRejected)
        self.assertEqual(result.code, RejectionCode.DEADLINE_PASSED)

    def test_action_and_deadline_at_same_timestamp_deadline_wins(self) -> None:
        due = NOW + timedelta(seconds=10)
        state = make_coding_room(due_at=due)
        request = RequestOfficialTestRun(
            request_id="test-at-deadline", player_id="p1", source_revision_id="revision-1"
        )

        action = apply_command(state, request, due)
        timeout = process_deadline(state, "coding-1", due)

        self.assertIsInstance(action, TransitionRejected)
        self.assertEqual(action.code, RejectionCode.DEADLINE_PASSED)
        self.assertIsInstance(timeout, TransitionAccepted)
        self.assertEqual(timeout.state.phase, GamePhase.ROUND_RESULT)


if __name__ == "__main__":
    unittest.main()
