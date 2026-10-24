"""Protocol v1 accepts only bounded, well-shaped client messages."""

import unittest

from pydantic import ValidationError

from app.api.websocket import room_websocket
from app.api.websocket_schemas import (
    MAX_MESSAGE_BYTES, ClientCommand, ClientPing, ClientSnapshotRequest,
    client_message_adapter,
)
from _support import DISCONNECT, FakeSocket, raw_frame, run_socket, text_frame


class ProtocolTests(unittest.TestCase):
    def test_valid_envelopes_decode_to_the_expected_models(self) -> None:
        examples = (
            ({"version": 1, "type": "ping", "nonce": "n1"}, ClientPing),
            ({"version": 1, "type": "snapshot_request", "request_id": "r1"}, ClientSnapshotRequest),
            ({"version": 1, "type": "command", "request_id": "r2", "action": {"name": "set_ready", "ready": True}}, ClientCommand),
        )
        for payload, expected_type in examples:
            with self.subTest(payload=payload):
                self.assertIsInstance(client_message_adapter.validate_python(payload), expected_type)

    def test_malformed_json_and_unknown_action_are_rejected_before_dispatch(self) -> None:
        socket = FakeSocket([
            raw_frame('{"version":1,"type":"ping",'),
            text_frame({"version": 1, "type": "command", "request_id": "r1", "action": {"name": "invented"}}),
            DISCONNECT,
        ])
        run_socket(room_websocket(socket))
        self.assertEqual([item["code"] for item in socket.sent[1:]], ["INVALID_MESSAGE", "INVALID_MESSAGE"])
        self.assertEqual(socket.closed, [])

    def test_duplicate_json_keys_are_rejected(self) -> None:
        socket = FakeSocket([raw_frame('{"version":1,"type":"ping","nonce":"a","nonce":"b"}'), DISCONNECT])
        run_socket(room_websocket(socket))
        self.assertEqual(socket.sent[1]["code"], "INVALID_MESSAGE")

    def test_wrong_version_reports_error_and_closes(self) -> None:
        socket = FakeSocket([text_frame({"version": 2, "type": "ping", "nonce": "n1"})])
        run_socket(room_websocket(socket))
        self.assertEqual(socket.sent[1]["code"], "UNSUPPORTED_VERSION")
        self.assertEqual(socket.closed, [1002])

    def test_oversized_utf8_frame_closes_before_json_parsing(self) -> None:
        socket = FakeSocket([raw_frame("é" * (MAX_MESSAGE_BYTES // 2 + 1))])
        run_socket(room_websocket(socket))
        self.assertEqual(socket.closed, [1009])
        self.assertEqual([message["type"] for message in socket.sent], ["snapshot"])

    def test_extra_identity_field_is_not_part_of_command_contract(self) -> None:
        with self.assertRaises(ValidationError):
            client_message_adapter.validate_python({
                "version": 1, "type": "command", "request_id": "r1",
                "player_id": "player-1", "action": {"name": "set_ready", "ready": True},
            })
