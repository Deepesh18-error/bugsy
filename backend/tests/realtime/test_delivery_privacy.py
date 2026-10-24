"""Public facts fan out; roles, ballots, and objectives stay player-private."""

from dataclasses import replace
from datetime import timedelta
import unittest

from app.game.events import (
    PlayerReadinessChanged, PlayerRoleAssigned, SabotageObjectiveVerified,
)
from app.game.models import (
    DeadlineKind, GameDeadline, GamePhase, MatchState, PlayerRole,
    RoundState, SabotageObjectiveProgress,
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

    def test_snapshot_contains_only_the_recipients_private_state(self) -> None:
        room = make_room()
        players = (
            replace(room.players[0], role=PlayerRole.CIVILIAN),
            replace(room.players[1], role=PlayerRole.IMPOSTOR),
        )
        deadline = GameDeadline("round-1", DeadlineKind.CODING_ROUND, NOW + timedelta(minutes=5))
        round_state = RoundState(
            number=1, category_id="object-oriented", challenge_id="counter",
            challenge_version="1.0.0", challenge_content_digest="sha256:example",
            started_at=NOW, deadline=deadline, current_source_revision_id="revision-1",
            sabotage_objectives=(SabotageObjectiveProgress(objective_id="objective-1"),),
        )
        room = replace(room, players=players, phase=GamePhase.CODING_ROUND,
                       phase_deadline=deadline, match=MatchState(round_number=1, current_round=round_state))
        civilian = room_snapshot(room, "player-1", 3).model_dump(mode="json")["room"]
        impostor = room_snapshot(room, "player-2", 3).model_dump(mode="json")["room"]
        self.assertEqual(civilian["own_role"], "civilian")
        self.assertEqual(civilian["own_objectives"], [])
        self.assertEqual(impostor["own_role"], "impostor")
        self.assertEqual(impostor["own_objectives"][0]["objective_id"], "objective-1")
        self.assertTrue(all("role" not in player and "objectives" not in player
                            for player in civilian["players"] + impostor["players"]))
