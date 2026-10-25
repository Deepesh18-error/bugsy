"""Player ballot validation, privacy, ties, skips, and resolution."""

from datetime import timedelta
import unittest

from app.game.commands import CastPlayerVote
from app.game.events import PlayerBallotStored, PlayerEliminated, PlayerVoteResolved
from app.game.models import GamePhase
from app.game.outcomes import RejectionCode, TransitionAccepted, TransitionRejected
from app.game.transitions import apply_command, resolve_player_vote

from _builders import NOW, make_players, make_voting_room


class VotingTests(unittest.TestCase):
    def test_one_voter_cannot_cast_two_ballots(self) -> None:
        state = make_voting_room()
        first = apply_command(
            state,
            CastPlayerVote(request_id="vote-1", player_id="p1", target_player_id="p4"),
            NOW,
        )
        self.assertIsInstance(first, TransitionAccepted)

        duplicate = apply_command(
            first.state,
            CastPlayerVote(request_id="vote-2", player_id="p1", target_player_id="p2"),
            NOW + timedelta(seconds=1),
        )

        self.assertIsInstance(duplicate, TransitionRejected)
        self.assertEqual(duplicate.code, RejectionCode.ALREADY_VOTED)

    def test_vote_rejects_unknown_or_ineligible_target(self) -> None:
        state = make_voting_room()
        result = apply_command(
            state,
            CastPlayerVote(
                request_id="vote-invalid", player_id="p1", target_player_id="missing"
            ),
            NOW,
        )

        self.assertIsInstance(result, TransitionRejected)
        self.assertEqual(result.code, RejectionCode.INVALID_VOTE_TARGET)

    def test_ballot_acknowledgement_does_not_reveal_target(self) -> None:
        state = make_voting_room()
        result = apply_command(
            state,
            CastPlayerVote(request_id="vote-private", player_id="p1", target_player_id="p4"),
            NOW,
        )

        self.assertIsInstance(result, TransitionAccepted)
        ballot_event = result.events[0]
        self.assertIsInstance(ballot_event, PlayerBallotStored)
        self.assertEqual(ballot_event.recipient_player_id, "p1")
        self.assertFalse(hasattr(ballot_event, "target_id"))
        self.assertFalse(hasattr(ballot_event, "target_player_id"))
        self.assertEqual(result.state.match.player_votes[0].target_id, "p4")

    def test_tied_votes_eject_nobody_and_resume_coding(self) -> None:
        state = make_voting_room()
        ballots = (("p1", "p3"), ("p2", "p4"), ("p3", "p3"), ("p4", "p4"))
        result = None
        for index, (voter, target) in enumerate(ballots):
            result = apply_command(
                state,
                CastPlayerVote(
                    request_id=f"tie-{index}", player_id=voter, target_player_id=target
                ),
                NOW + timedelta(seconds=index),
            )
            self.assertIsInstance(result, TransitionAccepted)
            state = result.state

        self.assertEqual(result.state.phase, GamePhase.CODING_ROUND)
        self.assertTrue(all(player.is_alive for player in result.state.players))
        resolution = next(event for event in result.events if isinstance(event, PlayerVoteResolved))
        self.assertTrue(resolution.was_tie)
        self.assertIsNone(resolution.ejected_player_id)
        self.assertEqual(
            result.state.match.current_round.deadline.due_at,
            NOW + timedelta(seconds=120) + timedelta(seconds=13),
        )

    def test_skip_votes_count_as_abstentions_and_eject_no_one(self) -> None:
        state = make_voting_room(due_at=NOW + timedelta(seconds=5))
        result = apply_command(
            state,
            CastPlayerVote(request_id="skip-1", player_id="p1", target_player_id=None),
            NOW,
        )
        self.assertIsInstance(result, TransitionAccepted)

        resolved = resolve_player_vote(
            result.state,
            NOW + timedelta(seconds=5),
            deadline_id="vote-1",
        )

        self.assertIsInstance(resolved, TransitionAccepted)
        self.assertEqual(resolved.state.phase, GamePhase.CODING_ROUND)
        resolution = next(event for event in resolved.events if isinstance(event, PlayerVoteResolved))
        self.assertEqual(resolution.skip_count, 1)
        self.assertIsNone(resolution.ejected_player_id)

    def test_zero_ballots_at_deadline_is_a_no_ejection_result(self) -> None:
        state = make_voting_room(due_at=NOW + timedelta(seconds=5))

        result = resolve_player_vote(
            state,
            NOW + timedelta(seconds=5),
            deadline_id="vote-1",
        )

        self.assertIsInstance(result, TransitionAccepted)
        resolution = next(event for event in result.events if isinstance(event, PlayerVoteResolved))
        self.assertEqual(resolution.vote_counts, ())
        self.assertIsNone(resolution.ejected_player_id)

    def test_skip_tie_blocks_an_ejection_and_is_saved_for_reconnect(self) -> None:
        state = make_voting_room()
        ballots = (("p1", None), ("p2", None), ("p3", "p4"), ("p4", "p4"))
        for index, (voter, target) in enumerate(ballots):
            result = apply_command(
                state,
                CastPlayerVote(request_id=f"skip-tie-{index}", player_id=voter, target_player_id=target),
                NOW + timedelta(seconds=index),
            )
            state = result.state
        self.assertEqual(state.phase, GamePhase.CODING_ROUND)
        self.assertIsNone(state.match.last_vote_result.ejected_player_id)
        self.assertTrue(state.match.last_vote_result.was_tie)
        self.assertEqual(state.match.last_vote_result.skip_count, 2)

    def test_disconnected_player_cannot_vote_and_does_not_block_eligible_ballots(self) -> None:
        state = make_voting_room(players=make_players(disconnected=frozenset({"p4"})))
        disconnected_vote = apply_command(
            state,
            CastPlayerVote(request_id="offline-vote", player_id="p4", target_player_id="p1"),
            NOW,
        )
        self.assertIsInstance(disconnected_vote, TransitionRejected)
        self.assertEqual(disconnected_vote.code, RejectionCode.PLAYER_NOT_CONNECTED)

        result = None
        for index, (voter, target) in enumerate((("p1", "p2"), ("p2", "p2"), ("p3", "p1"))):
            result = apply_command(
                state,
                CastPlayerVote(
                    request_id=f"connected-vote-{index}",
                    player_id=voter,
                    target_player_id=target,
                ),
                NOW + timedelta(seconds=index),
            )
            self.assertIsInstance(result, TransitionAccepted)
            state = result.state

        self.assertEqual(result.state.phase, GamePhase.CODING_ROUND)
        disconnected = next(player for player in result.state.players if player.player_id == "p4")
        self.assertTrue(disconnected.is_alive)
        self.assertEqual(disconnected.connection.value, "disconnected")
        self.assertEqual(result.state.match.last_vote_result.ejected_player_id, "p2")

    def test_impostor_is_ejected_once_and_match_ends(self) -> None:
        state = make_voting_room()
        result = None
        ballots = (("p1", "p4"), ("p2", "p4"), ("p3", "p4"), ("p4", "p3"))
        for index, (voter, target) in enumerate(ballots):
            result = apply_command(
                state,
                CastPlayerVote(
                    request_id=f"eject-{index}", player_id=voter, target_player_id=target
                ),
                NOW + timedelta(seconds=index),
            )
            self.assertIsInstance(result, TransitionAccepted)
            state = result.state

        self.assertEqual(result.state.phase, GamePhase.GAME_OVER)
        self.assertEqual(result.state.match.result.winner.value, "civilians")
        self.assertEqual(
            sum(isinstance(event, PlayerEliminated) for event in result.events), 1
        )
        repeated = resolve_player_vote(
            result.state, NOW + timedelta(seconds=10), deadline_id="vote-1"
        )
        self.assertIsInstance(repeated, TransitionRejected)
        self.assertEqual(repeated.code, RejectionCode.WRONG_PHASE)


if __name__ == "__main__":
    unittest.main()
