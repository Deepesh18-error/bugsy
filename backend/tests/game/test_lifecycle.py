"""Full-round progression, reconnect grace, room expiry, and rematch rules."""

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import timedelta

from app.game.commands import LeaveRoom, RequestRematch, SendChatMessage, StartMatch
from app.game.events import HostTransferred, PlayerDeparted, RematchStarted, RoomClosed
from app.game.models import (
    ConnectionStatus, DeadlineKind, GamePhase, MatchEndReason,
    MatchResult, MatchState, MatchWinner,
)
from app.game.outcomes import RejectionCode, TransitionAccepted, TransitionRejected
from app.game.transitions import (
    apply_command,
    end_coding_round,
    expire_reconnect_grace,
    expire_room,
    mark_player_disconnected,
    process_deadline,
    resolve_category_vote,
    restore_player_connection,
    start_coding_round,
)
from _builders import (
    NOW, make_coding_room, make_deadline, make_discussion_room,
    make_lobby, make_round, make_voting_room,
)


class LifecycleTests(unittest.TestCase):
    def test_four_round_match_then_unanimous_rematch_resets_private_state(self) -> None:
        room = make_lobby(ready=True)
        category_deadline = make_deadline(
            "category-1", DeadlineKind.CATEGORY_VOTE, NOW + timedelta(seconds=10)
        )
        started = apply_command(
            room, StartMatch(request_id="start", player_id="p1"), NOW,
            next_deadline=category_deadline,
        )
        self.assertIsInstance(started, TransitionAccepted)
        reveal_deadline = make_deadline(
            "reveal-1", DeadlineKind.ROLE_REVEAL, NOW + timedelta(seconds=20)
        )
        selected = resolve_category_vote(
            started.state, category_deadline.due_at,
            selected_category_id="object-oriented", impostor_player_id="p4",
            role_reveal_deadline=reveal_deadline,
        )
        self.assertIsInstance(selected, TransitionAccepted)
        early_round = start_coding_round(
            selected.state, make_round(started_at=NOW + timedelta(seconds=19)),
            NOW + timedelta(seconds=19),
        )
        self.assertIsInstance(early_round, TransitionRejected)
        self.assertEqual(early_round.code, RejectionCode.DEADLINE_NOT_REACHED)

        current = selected.state
        for number in range(1, 5):
            entry_time = NOW + timedelta(seconds=20 + number * 150)
            challenge = make_round(number=number, started_at=entry_time)
            if number == 1:
                begun = process_deadline(
                    current, reveal_deadline.deadline_id, entry_time,
                    next_round=challenge,
                )
            else:
                begun = start_coding_round(current, challenge, entry_time)
            self.assertIsInstance(begun, TransitionAccepted)
            self.assertEqual(begun.state.phase, GamePhase.CODING_ROUND)
            finished = end_coding_round(
                begun.state, challenge.deadline.due_at,
                deadline_id=challenge.deadline.deadline_id,
            )
            self.assertIsInstance(finished, TransitionAccepted)
            current = finished.state
            self.assertEqual(
                current.phase,
                GamePhase.GAME_OVER if number == 4 else GamePhase.ROUND_RESULT,
            )

        self.assertEqual(current.match.result.reason, MatchEndReason.FINAL_DEADLINE_SURVIVED)
        for number, player_id in enumerate(("p1", "p2", "p3", "p4"), start=1):
            request = apply_command(
                current,
                RequestRematch(request_id=f"rematch-{number}", player_id=player_id),
                NOW + timedelta(seconds=800 + number),
            )
            self.assertIsInstance(request, TransitionAccepted)
            current = request.state
            if number < 4:
                self.assertEqual(current.phase, GamePhase.GAME_OVER)
            else:
                self.assertTrue(any(isinstance(event, RematchStarted) for event in request.events))
        self.assertEqual(current.phase, GamePhase.LOBBY)
        self.assertIsNone(current.match)
        self.assertTrue(all(player.role is None and not player.is_ready for player in current.players))
        self.assertTrue(all(player.emergency_meetings_used == 0 for player in current.players))

    def test_reconnect_before_grace_preserves_identity_and_late_callback_is_stale(self) -> None:
        room = make_coding_room()
        grace = make_deadline(
            "grace-p2", DeadlineKind.RECONNECT_GRACE, NOW + timedelta(seconds=30)
        )
        lost = mark_player_disconnected(room, "p2", grace, NOW)
        self.assertIsInstance(lost, TransitionAccepted)
        self.assertEqual(lost.state.players[1].connection, ConnectionStatus.DISCONNECTED)
        blocked = apply_command(
            lost.state,
            SendChatMessage(request_id="chat", player_id="p2", message="hello"),
            NOW + timedelta(seconds=1),
        )
        self.assertIsInstance(blocked, TransitionRejected)
        restored = restore_player_connection(lost.state, "p2", NOW + timedelta(seconds=29))
        self.assertIsInstance(restored, TransitionAccepted)
        self.assertEqual(restored.state.players[1].player_id, "p2")
        self.assertEqual(restored.state.players[1].role, room.players[1].role)
        callback = expire_reconnect_grace(restored.state, "p2", grace.deadline_id, grace.due_at)
        self.assertIsInstance(callback, TransitionRejected)
        self.assertEqual(callback.code, RejectionCode.STALE_DEADLINE)

    def test_grace_deadline_wins_and_departed_host_transfers(self) -> None:
        room = make_coding_room()
        grace = make_deadline(
            "grace-host", DeadlineKind.RECONNECT_GRACE, NOW + timedelta(seconds=30)
        )
        lost = mark_player_disconnected(room, "p1", grace, NOW)
        self.assertIsInstance(lost, TransitionAccepted)
        late = restore_player_connection(lost.state, "p1", grace.due_at)
        self.assertIsInstance(late, TransitionRejected)
        self.assertEqual(late.code, RejectionCode.RECONNECT_GRACE_EXPIRED)
        early_callback = expire_reconnect_grace(
            lost.state, "p1", grace.deadline_id, NOW + timedelta(seconds=29)
        )
        self.assertIsInstance(early_callback, TransitionRejected)
        departed = expire_reconnect_grace(lost.state, "p1", grace.deadline_id, grace.due_at)
        self.assertIsInstance(departed, TransitionAccepted)
        self.assertEqual(departed.state.host_player_id, "p2")
        self.assertEqual(departed.state.players[0].connection, ConnectionStatus.DEPARTED)
        self.assertTrue(any(isinstance(event, HostTransferred) for event in departed.events))
        self.assertTrue(any(isinstance(event, PlayerDeparted) for event in departed.events))

    def test_room_expiry_works_during_a_round_and_does_not_apply_twice(self) -> None:
        room = make_coding_room()
        expiry = expire_room(room, room.expires_at)
        self.assertIsInstance(expiry, TransitionAccepted)
        self.assertTrue(expiry.state.is_closed)
        self.assertTrue(any(isinstance(event, RoomClosed) for event in expiry.events))
        repeated = expire_room(expiry.state, room.expires_at + timedelta(seconds=1))
        self.assertIsInstance(repeated, TransitionRejected)
        command = apply_command(
            room,
            SendChatMessage(request_id="late", player_id="p1", message="too late"),
            room.expires_at,
        )
        self.assertIsInstance(command, TransitionRejected)
        self.assertEqual(command.code, RejectionCode.ROOM_CLOSED)

    def test_disconnect_and_reconnect_preserve_each_phase(self) -> None:
        lobby = make_lobby()
        category = replace(
            lobby,
            phase=GamePhase.CATEGORY_VOTE,
            match=MatchState(),
            phase_deadline=make_deadline(
                "category", DeadlineKind.CATEGORY_VOTE, NOW + timedelta(seconds=60)
            ),
        )
        reveal = replace(
            category,
            phase=GamePhase.ROLE_REVEAL,
            match=MatchState(selected_category_id="object-oriented"),
            phase_deadline=make_deadline(
                "reveal", DeadlineKind.ROLE_REVEAL, NOW + timedelta(seconds=60)
            ),
        )
        coding = make_coding_room()
        discussion = make_discussion_room()
        vote = make_voting_room()
        round_result = replace(coding, phase=GamePhase.ROUND_RESULT, phase_deadline=None)
        game_over = replace(
            coding,
            phase=GamePhase.GAME_OVER,
            phase_deadline=None,
            match=replace(
                coding.match,
                result=MatchResult(
                    winner=MatchWinner.CIVILIANS,
                    reason=MatchEndReason.REQUIRED_TESTS_PASSED,
                    round_number=1,
                    ended_at=NOW,
                ),
            ),
        )
        for room in (lobby, category, reveal, coding, discussion, vote, round_result, game_over):
            with self.subTest(phase=room.phase):
                grace = make_deadline(
                    f"grace-{room.phase.value}", DeadlineKind.RECONNECT_GRACE,
                    NOW + timedelta(seconds=30),
                )
                lost = mark_player_disconnected(room, "p2", grace, NOW)
                self.assertIsInstance(lost, TransitionAccepted)
                restored = restore_player_connection(
                    lost.state, "p2", NOW + timedelta(seconds=1)
                )
                self.assertIsInstance(restored, TransitionAccepted)
                self.assertEqual(restored.state.phase, room.phase)
                self.assertEqual(restored.state.phase_deadline, room.phase_deadline)
                self.assertEqual(restored.state.match, room.match)
                self.assertEqual(restored.state.players[1], room.players[1])

    def test_impostor_departure_ends_match_for_civilians(self) -> None:
        room = make_coding_room()
        left = apply_command(
            room, LeaveRoom(request_id="impostor-leaves", player_id="p4"), NOW
        )
        self.assertIsInstance(left, TransitionAccepted)
        self.assertEqual(left.state.phase, GamePhase.GAME_OVER)
        self.assertEqual(left.state.match.result.reason, MatchEndReason.IMPOSTOR_DEPARTED)
        self.assertEqual(left.state.match.result.winner, MatchWinner.CIVILIANS)
        self.assertIsNone(left.state.phase_deadline)

    def test_category_vote_closes_if_departures_leave_too_few_players(self) -> None:
        room = replace(
            make_lobby(),
            phase=GamePhase.CATEGORY_VOTE,
            match=MatchState(),
            phase_deadline=make_deadline(
                "category", DeadlineKind.CATEGORY_VOTE, NOW + timedelta(seconds=30)
            ),
        )
        left = apply_command(room, LeaveRoom(request_id="early-exit", player_id="p2"), NOW)
        self.assertIsInstance(left, TransitionAccepted)
        self.assertTrue(left.state.is_closed)
        self.assertTrue(any(isinstance(event, RoomClosed) for event in left.events))


if __name__ == "__main__":
    unittest.main()
