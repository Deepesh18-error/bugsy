"""Idle, malformed, oversized, and rapid traffic cannot retain dead sockets."""

import asyncio
import unittest
from unittest.mock import patch

from app.api.websocket import MAX_MESSAGE_BYTES, MAX_MESSAGES_PER_WINDOW, room_websocket
from app.realtime.connection_manager import RoomConnectionManager
from _support import DISCONNECT, FakeSocket, raw_frame, run_socket, text_frame


PING = {"version": 1, "type": "ping", "nonce": "heartbeat"}


class ConnectionLimitTests(unittest.TestCase):
    def test_ping_receives_pong_then_idle_timeout_closes_and_unregisters(self) -> None:
        socket = FakeSocket([text_frame(PING)])

        async def timeout_on_empty(awaitable: object, *, timeout: float) -> object:
            if not socket.frames:
                awaitable.close()
                raise asyncio.TimeoutError()
            return await awaitable

        with patch("app.api.websocket.asyncio.wait_for", timeout_on_empty):
            try:
                room_websocket(socket).send(None)
            except StopIteration:
                pass
            else:
                self.fail("The fake WebSocket unexpectedly yielded.")
        self.assertEqual([item["type"] for item in socket.sent], ["snapshot", "pong"])
        self.assertEqual(socket.closed, [1001])
        self.assertFalse(socket.manager._connections)

    def test_oversized_and_binary_frames_close_without_reaching_command_layer(self) -> None:
        oversized = FakeSocket([raw_frame("x" * (MAX_MESSAGE_BYTES + 1))])
        run_socket(room_websocket(oversized))
        self.assertEqual(oversized.closed, [1009])
        binary = FakeSocket([{"type": "websocket.receive", "text": None, "bytes": b"data"}])
        run_socket(room_websocket(binary))
        self.assertEqual(binary.closed, [1003])
        self.assertFalse(oversized.manager._connections)
        self.assertFalse(binary.manager._connections)

    def test_rate_limit_closes_after_allowed_window(self) -> None:
        socket = FakeSocket([text_frame(PING) for _ in range(MAX_MESSAGES_PER_WINDOW + 1)])
        with patch("app.api.websocket.monotonic", return_value=100.0):
            run_socket(room_websocket(socket))
        self.assertEqual(socket.closed, [1008])
        self.assertEqual(sum(item["type"] == "pong" for item in socket.sent), MAX_MESSAGES_PER_WINDOW)
        self.assertFalse(socket.manager._connections)

    def test_repeated_disconnect_cleanup_is_idempotent(self) -> None:
        manager = RoomConnectionManager()
        socket = FakeSocket([])
        connection = manager.register("ABCDEFG2", "player-2", socket)
        manager.unregister(connection)
        manager.unregister(connection)
        self.assertFalse(manager._connections)
        received = FakeSocket([DISCONNECT])
        run_socket(room_websocket(received))
        self.assertFalse(received.manager._connections)
