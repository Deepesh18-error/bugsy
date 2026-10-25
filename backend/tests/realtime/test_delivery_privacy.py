"""Public facts fan out; roles, ballots, and objectives stay player-private."""

from dataclasses import replace
from datetime import timedelta
import unittest

from app.challenges.loader import load_challenge
from app.game.events import (
    PlayerBallotStored, PlayerReadinessChanged, PlayerRoleAssigned,
    PlayerVoteResolved, SabotageObjectiveVerified,
)
from app.game.models import (
    DeadlineKind, GameDeadline, GamePhase, MatchState, PlayerRole,
    RoundState, SabotageObjectiveProgress, Vote, VoteKind,
)
from app.realtime.connection_manager import RoomConnectionManager
from app.realtime.snapshots import project_event, room_snapshot
from _support import NOW, FakeSocket, make_room, run_socket


class DeliveryPrivacyTests(unittest.TestCase):
    def test_public_event_reaches_every_room_member_but_no_other_room(self) -> None:
        manager = RoomConnectionManager()
        first, second, outsider = (FakeSocket([]) for _ in range(3))
        manager.register("ABCDEFG2", "player-1", first)
        manager.register("ABCDEFG2", "player-2", second)
        manager.register("OTHERROOM", "player-3", outsider)
        recipient, wire_event = project_event(PlayerReadinessChanged(
            occurred_at=NOW, request_id="r1", player_id="player-1", is_ready=True,
        ), 4)
        self.assertIsNone(recipient)
        run_socket(manager.broadcast("ABCDEFG2", wire_event))
        self.assertEqual(first.sent, second.sent)
        self.assertEqual(first.sent[0]["sequence"], 4)
        self.assertEqual(first.sent[0]["payload"], {"player_id": "player-1", "is_ready": True})
        self.assertEqual(outsider.sent, [])

    def test_role_and_objective_events_reach_only_named_player(self) -> None:
        manager = RoomConnectionManager()
        civilian, impostor = FakeSocket([]), FakeSocket([])
        manager.register("ABCDEFG2", "player-1", civilian)
        manager.register("ABCDEFG2", "player-2", impostor)
        private_facts = (
            PlayerRoleAssigned(occurred_at=NOW, request_id=None,
                               recipient_player_id="player-2", role=PlayerRole.IMPOSTOR),
            SabotageObjectiveVerified(occurred_at=NOW, request_id=None,
                                       recipient_player_id="player-2", objective_id="objective-1",
                                       source_revision_id="revision-1"),
        )
        for fact in private_facts:
            recipient, wire_event = project_event(fact, 7)
            self.assertEqual(recipient, "player-2")
            run_socket(manager.send_private("ABCDEFG2", recipient, wire_event))
        self.assertEqual(civilian.sent, [])
        self.assertEqual([item["name"] for item in impostor.sent],
                         ["PlayerRoleAssigned", "SabotageObjectiveVerified"])
        self.assertNotIn("objective-1", repr(civilian.sent))

    def test_ballot_event_is_private_and_only_resolution_aggregate_is_public(self) -> None:
        manager = RoomConnectionManager()
        players = [FakeSocket([]) for _ in range(3)]
        for player_id, socket in zip(("player-1", "player-2", "player-3"), players):
            manager.register("ABCDEFG2", player_id, socket)

        recipient, private_ballot = project_event(PlayerBallotStored(
            occurred_at=NOW,
            request_id="ballot-request",
            recipient_player_id="player-2",
            is_skip=False,
        ), 8)
        self.assertEqual(recipient, "player-2")
        self.assertEqual(private_ballot.payload, {"is_skip": False})
        run_socket(manager.send_private("ABCDEFG2", recipient, private_ballot))
        self.assertEqual([len(socket.sent) for socket in players], [0, 1, 0])

        recipient, public_result = project_event(PlayerVoteResolved(
            occurred_at=NOW,
            request_id="ballot-request",
            vote_counts=(("player-3", 2),),
            skip_count=1,
            ejected_player_id="player-3",
            was_tie=False,
        ), 9)
        self.assertIsNone(recipient)
        self.assertEqual(set(public_result.payload), {
            "vote_counts", "skip_count", "ejected_player_id", "was_tie",
        })
        self.assertNotIn("voter_id", repr(public_result.payload))
        run_socket(manager.broadcast("ABCDEFG2", public_result))
        self.assertEqual([len(socket.sent) for socket in players], [1, 2, 1])
        self.assertEqual(
            players[0].sent[0]["payload"],
            {"vote_counts": {"player-3": 2}, "skip_count": 1,
             "ejected_player_id": "player-3", "was_tie": False},
        )

    def test_authorized_snapshot_restores_only_the_own_player_ballot(self) -> None:
        room = make_room()
        own_ballot = Vote(
            kind=VoteKind.PLAYER,
            voter_id="player-2",
            target_id="player-1",
            request_id="private-vote",
            cast_at=NOW,
        )
        deadline = GameDeadline(
            "player-vote-1", DeadlineKind.PLAYER_VOTE, NOW + timedelta(minutes=1)
        )
        voting = replace(
            room,
            phase=GamePhase.PLAYER_VOTE,
            phase_deadline=deadline,
            match=MatchState(player_votes=(own_ballot,)),
        )
        voter = room_snapshot(voting, "player-2", 4).model_dump(mode="json")["room"]
        observer = room_snapshot(voting, "player-1", 4).model_dump(mode="json")["room"]

        self.assertTrue(voter["has_cast_player_vote"])
        self.assertEqual(voter["own_player_vote_target_id"], "player-1")
        self.assertFalse(observer["has_cast_player_vote"])
        self.assertIsNone(observer["own_player_vote_target_id"])
        self.assertNotIn("player_votes", repr(voter))

    def test_snapshot_contains_only_the_recipients_private_state(self) -> None:
        room = make_room()
        loaded = load_challenge("oop.counter", "1.0.0")
        players = (
            replace(room.players[0], role=PlayerRole.CIVILIAN),
            replace(room.players[1], role=PlayerRole.IMPOSTOR),
        )
        deadline = GameDeadline("round-1", DeadlineKind.CODING_ROUND, NOW + timedelta(minutes=5))
        round_state = RoundState(
            number=1, category_id="object-oriented", challenge_id=loaded.challenge.id,
            challenge_version=loaded.challenge.version,
            challenge_content_digest=loaded.content_digest,
            started_at=NOW, deadline=deadline, current_source_revision_id="revision-1",
            sabotage_objectives=(SabotageObjectiveProgress(objective_id="regress-decrement"),),
        )
        room = replace(room, players=players, phase=GamePhase.CODING_ROUND,
                       phase_deadline=deadline, match=MatchState(round_number=1, current_round=round_state))
        civilian = room_snapshot(room, "player-1", 3).model_dump(mode="json")["room"]
        impostor = room_snapshot(room, "player-2", 3).model_dump(mode="json")["room"]
        self.assertEqual(civilian["own_role"], "civilian")
        self.assertEqual(civilian["own_objectives"], [])
        self.assertEqual(impostor["own_role"], "impostor")
        self.assertEqual(impostor["own_objectives"][0]["objective_id"], "regress-decrement")
        self.assertEqual(
            impostor["own_objectives"][0]["private_description"],
            loaded.challenge.sabotage_objectives[0].private_description,
        )
        self.assertTrue(all("role" not in player and "objectives" not in player
                            for player in civilian["players"] + impostor["players"]))
