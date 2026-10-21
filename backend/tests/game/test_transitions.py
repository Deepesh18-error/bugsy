"""Command acceptance and rejection scenarios for the game transitions."""

from dataclasses import replace
from datetime import timedelta
import unittest

from app.game.commands import SetReady, StartMatch
from app.game.events import MatchStarted, PlayerReadinessChanged
from app.game.models import DeadlineKind, GamePhase, MatchState
from app.game.outcomes import RejectionCode, TransitionAccepted, TransitionRejected
from app.game.transitions import apply_command

from _builders import NOW, make_deadline, make_lobby


class TransitionTests(unittest.TestCase):
    def test_set_ready_returns_new_state_and_event_without_mutating_input(self) -> None:
        state = make_lobby()
        command = SetReady(request_id="ready-1", player_id="p2", ready=True)

        result = apply_command(state, command, NOW)

        self.assertIsInstance(result, TransitionAccepted)
        self.assertFalse(state.players[1].is_ready)
        self.assertTrue(result.state.players[1].is_ready)
        self.assertEqual(len(result.events), 1)
        self.assertIsInstance(result.events[0], PlayerReadinessChanged)
        self.assertEqual(result.events[0].player_id, "p2")

    def test_set_ready_rejects_actions_outside_lobby(self) -> None:
        state = make_lobby()
        state = replace(
            state,
            phase=GamePhase.CATEGORY_VOTE,
            match=MatchState(),
        )
        command = SetReady(request_id="ready-2", player_id="p2", ready=True)

        result = apply_command(state, command, NOW)

        self.assertIsInstance(result, TransitionRejected)
        self.assertEqual(result.code, RejectionCode.WRONG_PHASE)
        self.assertIs(result.state, state)

    def test_start_match_requires_the_host(self) -> None:
        state = make_lobby(ready=True)
        result = apply_command(
            state,
            StartMatch(request_id="start-1", player_id="p2"),
            NOW,
            next_deadline=make_deadline(
                "category-1", DeadlineKind.CATEGORY_VOTE, NOW + timedelta(seconds=20)
            ),
        )

        self.assertIsInstance(result, TransitionRejected)
        self.assertEqual(result.code, RejectionCode.NOT_HOST)
        self.assertIs(result.state, state)

    def test_start_match_requires_every_connected_player_ready(self) -> None:
        state = make_lobby(ready=False)
        result = apply_command(
            state,
            StartMatch(request_id="start-2", player_id="p1"),
            NOW,
            next_deadline=make_deadline(
                "category-2", DeadlineKind.CATEGORY_VOTE, NOW + timedelta(seconds=20)
            ),
        )

        self.assertIsInstance(result, TransitionRejected)
        self.assertEqual(result.code, RejectionCode.NOT_READY)

    def test_valid_host_start_moves_room_to_category_vote(self) -> None:
        state = make_lobby(ready=True)
        deadline = make_deadline(
            "category-3", DeadlineKind.CATEGORY_VOTE, NOW + timedelta(seconds=20)
        )

        result = apply_command(
            state,
            StartMatch(request_id="start-3", player_id="p1"),
            NOW,
            next_deadline=deadline,
        )

        self.assertIsInstance(result, TransitionAccepted)
        self.assertEqual(result.state.phase, GamePhase.CATEGORY_VOTE)
        self.assertEqual(result.state.phase_deadline, deadline)
        self.assertIsNotNone(result.state.match)
        self.assertEqual(result.events[0], MatchStarted(
            occurred_at=NOW, request_id="start-3", room_code="TEST42"
        ))


if __name__ == "__main__":
    unittest.main()
