"""Live commands use cookie identity, game rules, and durable receipts."""

from dataclasses import replace
from datetime import timedelta
import unittest

from app.api.websocket import room_websocket
from app.game.models import DeadlineKind, GameDeadline, GamePhase, MatchState
from app.realtime.coordinator import RoomCoordinator
from _support import DISCONNECT, NOW, FakeRepository, FakeService, FakeSocket, make_room, run_socket, text_frame


def command(request_id: str, action: dict[str, object], **extra: object) -> dict[str, object]:
    return {"version": 1, "type": "command", "request_id": request_id, "action": action, **extra}


class CommandTests(unittest.TestCase):
    def run_commands(self, repository: FakeRepository, messages: list[dict[str, object]]) -> FakeSocket:
        socket = FakeSocket([*(text_frame(item) for item in messages), DISCONNECT], service=FakeService(repository.stored.state))
        socket.app.state.room_coordinator = RoomCoordinator(repository, socket.manager)
        run_socket(room_websocket(socket))
        return socket

    def test_ready_updates_only_authenticated_player_and_persists_before_ack(self) -> None:
        repository = FakeRepository()
        socket = self.run_commands(repository, [command("r1", {"name": "set_ready", "ready": True})])
        players = {item.player_id: item for item in repository.stored.state.players}
        self.assertFalse(players["player-1"].is_ready)
        self.assertTrue(players["player-2"].is_ready)
        self.assertEqual(repository.commits, 1)
        self.assertEqual([item["type"] for item in socket.sent], ["snapshot", "event", "ack"])
        self.assertEqual(socket.sent[-1]["sequence"], repository.stored.sequence)
        self.assertEqual(socket.sent[1]["payload"]["player_id"], "player-2")

    def test_spoofed_player_field_is_rejected_without_reaching_engine(self) -> None:
        repository = FakeRepository()
        socket = self.run_commands(repository, [command("r1", {"name": "set_ready", "ready": True}, player_id="player-1")])
        self.assertEqual(socket.sent[1]["code"], "INVALID_MESSAGE")
        self.assertEqual(repository.commits, 0)

    def test_valid_command_in_wrong_phase_is_rejected_without_state_change(self) -> None:
        room = replace(
            make_room(), phase=GamePhase.CATEGORY_VOTE, match=MatchState(),
            phase_deadline=GameDeadline("vote-1", DeadlineKind.CATEGORY_VOTE, NOW + timedelta(minutes=5)),
        )
        repository = FakeRepository(room)
        socket = self.run_commands(repository, [command("r1", {"name": "set_ready", "ready": True})])
        self.assertEqual(socket.sent[1]["code"], "wrong_phase")
        self.assertEqual(repository.stored.state, room)
        self.assertEqual(repository.stored.sequence, 0)
        self.assertEqual(repository.commits, 1)  # The rejection receipt is durable.

    def test_retry_returns_saved_ack_without_applying_action_twice(self) -> None:
        repository = FakeRepository()
        socket = self.run_commands(repository, [
            command("r1", {"name": "set_ready", "ready": True}),
            command("r1", {"name": "set_ready", "ready": True}),
            command("r1", {"name": "set_ready", "ready": False}),
        ])
        self.assertEqual(repository.commits, 1)
        self.assertEqual([item["type"] for item in socket.sent], ["snapshot", "event", "ack", "ack", "error"])
        self.assertEqual(socket.sent[2]["sequence"], socket.sent[3]["sequence"])
        self.assertEqual(socket.sent[4]["code"], "DUPLICATE_REQUEST")
