"""Reconnects start from an authorized snapshot and retries reuse receipts."""

from dataclasses import replace
import unittest

from app.api.websocket import room_websocket
from app.realtime.coordinator import RoomCoordinator
from _support import DISCONNECT, FakeRepository, FakeService, FakeSocket, run_socket, text_frame


def ready(request_id: str, value: bool = True) -> dict[str, object]:
    return {"version": 1, "type": "command", "request_id": request_id,
            "action": {"name": "set_ready", "ready": value}}


class CurrentRoomService(FakeService):
    def __init__(self, repository: FakeRepository) -> None:
        super().__init__(repository.stored.state)
        self.repository = repository

    async def authenticate_player(self, credential: str | None):
        guest = await super().authenticate_player(credential)
        return replace(guest, state=self.repository.stored.state, sequence=self.repository.stored.sequence)


class SequenceReconnectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = FakeRepository()
        self.service = CurrentRoomService(self.repository)

    def connect(self, frames: list[dict[str, object]]) -> FakeSocket:
        socket = FakeSocket(frames, service=self.service)
        socket.app.state.room_coordinator = RoomCoordinator(self.repository, socket.manager)
        run_socket(room_websocket(socket))
        return socket

    def test_reconnect_gets_full_current_snapshot_before_other_messages(self) -> None:
        original = self.connect([text_frame(ready("r1")), DISCONNECT])
        self.assertEqual(original.sent[-1]["type"], "ack")
        reconnect = self.connect([DISCONNECT])
        self.assertEqual([item["type"] for item in reconnect.sent], ["snapshot"])
        self.assertEqual(reconnect.sent[0]["sequence"], 1)
        self.assertTrue(next(player for player in reconnect.sent[0]["room"]["players"]
                             if player["player_id"] == "player-2")["is_ready"])

    def test_snapshot_request_catches_up_after_a_sequence_gap(self) -> None:
        self.connect([text_frame(ready("r1")), DISCONNECT])
        self.connect([text_frame(ready("r2", False)), DISCONNECT])
        reconnect = self.connect([
            text_frame({"version": 1, "type": "snapshot_request", "request_id": "gap-1"}),
            DISCONNECT,
        ])
        self.assertEqual([message["sequence"] for message in reconnect.sent], [2, 2])
        self.assertEqual(reconnect.sent[1]["request_id"], "gap-1")
        self.assertFalse(next(player for player in reconnect.sent[1]["room"]["players"]
                              if player["player_id"] == "player-2")["is_ready"])

    def test_retry_after_reconnect_reuses_ack_and_does_not_reapply(self) -> None:
        self.connect([text_frame(ready("r1")), DISCONNECT])
        retry = self.connect([text_frame(ready("r1")), DISCONNECT])
        self.assertEqual(self.repository.commits, 1)
        self.assertEqual([item["type"] for item in retry.sent], ["snapshot", "ack"])
        self.assertEqual(retry.sent[1]["sequence"], 1)

    def test_changed_payload_with_reused_request_id_is_rejected_after_reconnect(self) -> None:
        self.connect([text_frame(ready("r1")), DISCONNECT])
        retry = self.connect([text_frame(ready("r1", False)), DISCONNECT])
        self.assertEqual(retry.sent[1]["code"], "DUPLICATE_REQUEST")
        self.assertEqual(self.repository.commits, 1)
