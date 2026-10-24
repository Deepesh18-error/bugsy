"""Two guests share public room state but retain separate command identities."""

from datetime import timedelta
import unittest

from app.api.websocket_schemas import client_message_adapter
from app.realtime.connection_manager import RoomConnectionManager
from app.realtime.coordinator import RoomCoordinator
from app.realtime.snapshots import room_snapshot
from app.rooms.service import AuthenticatedGuest
from _support import NOW, FakeRepository, FakeSocket, run_socket


class MultiSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = FakeRepository()
        self.manager = RoomConnectionManager()
        self.coordinator = RoomCoordinator(self.repository, self.manager)
        self.first = FakeSocket([])
        self.second = FakeSocket([])
        room_code = self.repository.stored.state.room_code
        self.manager.register(room_code, "player-1", self.first)
        self.manager.register(room_code, "player-2", self.second)

    def guest(self, player_id: str) -> AuthenticatedGuest:
        return AuthenticatedGuest(self.repository.stored.state, player_id, NOW + timedelta(hours=1))

    def dispatch(self, player_id: str, request_id: str, ready: bool) -> object:
        message = client_message_adapter.validate_python({
            "version": 1, "type": "command", "request_id": request_id,
            "action": {"name": "set_ready", "ready": ready},
        })
        result: list[object] = []

        async def apply() -> None:
            result.append(await self.coordinator.dispatch(self.guest(player_id), message))

        run_socket(apply())
        return result[0]

    def test_both_members_receive_each_public_change_and_same_sequence(self) -> None:
        self.dispatch("player-1", "host-ready", True)
        self.dispatch("player-2", "guest-ready", True)
        self.assertEqual(self.first.sent, self.second.sent)
        self.assertEqual([item["sequence"] for item in self.first.sent], [1, 2])
        self.assertEqual([item["payload"]["player_id"] for item in self.first.sent],
                         ["player-1", "player-2"])
        first_snapshot = room_snapshot(self.repository.stored.state, "player-1", 2)
        second_snapshot = room_snapshot(self.repository.stored.state, "player-2", 2)
        self.assertEqual(first_snapshot.sequence, second_snapshot.sequence)
        self.assertEqual(first_snapshot.room.players, second_snapshot.room.players)
        self.assertEqual(first_snapshot.room.self_player_id, "player-1")
        self.assertEqual(second_snapshot.room.self_player_id, "player-2")

    def test_same_request_id_is_scoped_to_each_authenticated_guest(self) -> None:
        self.dispatch("player-1", "shared-id", True)
        self.dispatch("player-2", "shared-id", True)
        self.assertEqual(self.repository.commits, 2)
        self.assertEqual(set(key[1] for key in self.repository.receipts),
                         {"player-1", "player-2"})
        self.assertTrue(all(player.is_ready for player in self.repository.stored.state.players))

    def test_guest_action_cannot_change_other_players_ready_state(self) -> None:
        self.dispatch("player-2", "guest-ready", True)
        players = {player.player_id: player for player in self.repository.stored.state.players}
        self.assertFalse(players["player-1"].is_ready)
        self.assertTrue(players["player-2"].is_ready)
