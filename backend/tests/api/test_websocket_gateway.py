"""Security and handshake checks for the first WebSocket gateway increment."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.api.websocket import RoomConnectionManager, room_websocket
from app.api.websocket_schemas import client_message_adapter
from app.game.models import PlayerState, RoomState
from app.rooms.identity import credential_digest
from app.rooms.repository import GuestSession, StoredRoom
from app.rooms.service import AuthenticatedGuest, RoomService, RoomServiceError


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _room() -> RoomState:
    return RoomState(
        room_code="ABCDEFG2",
        host_player_id="player-1",
        players=(PlayerState(player_id="player-1", display_name="Ada", joined_at=NOW),),
        created_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )


class _FakeService:
    def __init__(self, guest: AuthenticatedGuest) -> None:
        self.guest = guest
        self.calls = 0
        self.invalidate_after_first = False

    async def authenticate_player(self, credential: str | None) -> AuthenticatedGuest:
        self.calls += 1
        if credential != "private-cookie" or (self.invalidate_after_first and self.calls > 1):
            raise RoomServiceError("SESSION_INVALID", "Invalid session.", 401)
        return self.guest


class _FakeSocket:
    def __init__(self, frames: list[dict[str, object]], *, origin: str = "http://127.0.0.1:5173") -> None:
        self.headers = {"origin": origin}
        self.url = SimpleNamespace(query="")
        self.cookies = {"codemafia_guest": "private-cookie"}
        self.service = _FakeService(
            AuthenticatedGuest(_room(), "player-1", NOW + timedelta(hours=1))
        )
        self.manager = RoomConnectionManager()
        self.app = SimpleNamespace(
            state=SimpleNamespace(
                allowed_origins=("http://127.0.0.1:5173",),
                room_service=self.service,
                room_connection_manager=self.manager,
                room_coordinator=None,
            )
        )
        self.frames = list(frames)
        self.sent: list[dict[str, object]] = []
        self.closed: list[int] = []
        self.accepted = False

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int, reason: str | None = None) -> None:
        self.closed.append(code)

    async def send_json(self, data: dict[str, object]) -> None:
        self.sent.append(data)

    async def receive(self) -> dict[str, object]:
        return self.frames.pop(0)


def _text_frame(value: dict[str, object]) -> dict[str, object]:
    return {"type": "websocket.receive", "text": json.dumps(value), "bytes": None}


DISCONNECT = {"type": "websocket.disconnect", "code": 1000}


async def _receive_without_loop(awaitable: object, *, timeout: float) -> object:
    """Drive immediate fake frames without opening Windows loop sockets."""

    return await awaitable


def _run_immediate(coroutine: object) -> None:
    with patch("app.api.websocket.asyncio.wait_for", _receive_without_loop):
        try:
            coroutine.send(None)
        except StopIteration:
            return
        raise AssertionError("A fake WebSocket operation unexpectedly yielded.")


class WebSocketGatewayTests(unittest.TestCase):
    def test_command_cannot_supply_another_player_id(self) -> None:
        with self.assertRaises(ValidationError):
            client_message_adapter.validate_python(
                {
                    "version": 1,
                    "type": "command",
                    "request_id": "req_1",
                    "player_id": "player-2",
                    "action": {"name": "set_ready", "ready": True},
                }
            )

    def test_unapproved_origin_is_denied_before_cookie_lookup(self) -> None:
        socket = _FakeSocket([], origin="https://untrusted.example")
        _run_immediate(room_websocket(socket))
        self.assertFalse(socket.accepted)
        self.assertEqual(socket.closed, [1008])
        self.assertEqual(socket.service.calls, 0)

    def test_missing_origin_and_query_credentials_are_denied_before_accept(self) -> None:
        missing_origin = _FakeSocket([])
        missing_origin.headers.clear()
        _run_immediate(room_websocket(missing_origin))
        self.assertEqual(missing_origin.closed, [1008])
        self.assertEqual(missing_origin.service.calls, 0)

        query_credential = _FakeSocket([])
        query_credential.url.query = "token=private-cookie"
        _run_immediate(room_websocket(query_credential))
        self.assertEqual(query_credential.closed, [1008])
        self.assertEqual(query_credential.service.calls, 0)

    def test_authorized_guest_gets_snapshot_and_pong(self) -> None:
        socket = _FakeSocket(
            [_text_frame({"version": 1, "type": "ping", "nonce": "n1"}), DISCONNECT]
        )
        _run_immediate(room_websocket(socket))
        self.assertTrue(socket.accepted)
        self.assertEqual([item["type"] for item in socket.sent], ["snapshot", "pong"])
        self.assertEqual(socket.sent[0]["room"]["self_player_id"], "player-1")
        self.assertEqual(socket.sent[1]["nonce"], "n1")
        self.assertNotIn("private-cookie", repr(socket.sent))
        self.assertFalse(socket.manager._connections)

    def test_command_is_not_acknowledged_without_coordinator(self) -> None:
        socket = _FakeSocket(
            [
                _text_frame({
                    "version": 1,
                    "type": "command",
                    "request_id": "req_1",
                    "action": {"name": "set_ready", "ready": True},
                }),
                DISCONNECT,
            ]
        )
        _run_immediate(room_websocket(socket))
        self.assertEqual(socket.sent[1]["type"], "error")
        self.assertEqual(socket.sent[1]["code"], "COMMANDS_UNAVAILABLE")
        self.assertNotIn("ack", [item["type"] for item in socket.sent])

    def test_oversized_message_is_closed_before_parsing(self) -> None:
        socket = _FakeSocket(
            [{"type": "websocket.receive", "text": "x" * 17_000, "bytes": None}]
        )
        _run_immediate(room_websocket(socket))
        self.assertEqual(socket.closed, [1009])
        self.assertEqual([item["type"] for item in socket.sent], ["snapshot"])

    def test_malformed_command_does_not_reach_coordinator(self) -> None:
        socket = _FakeSocket(
            [
                _text_frame({
                    "version": 1,
                    "type": "command",
                    "request_id": "req_1",
                    "player_id": "player-2",
                    "action": {"name": "set_ready", "ready": True},
                }),
                DISCONNECT,
            ]
        )
        _run_immediate(room_websocket(socket))
        self.assertEqual(socket.sent[1]["code"], "INVALID_MESSAGE")

    def test_client_cannot_claim_a_role_or_publish_an_official_result(self) -> None:
        for action in (
            {"name": "set_ready", "ready": True, "role": "impostor"},
            {"name": "official_test_result", "all_required_tests_passed": True},
            {"name": "send_chat_message", "message": "x" * 501},
        ):
            with self.subTest(action=action["name"]), self.assertRaises(ValidationError):
                client_message_adapter.validate_python({
                    "version": 1, "type": "command", "request_id": "req-1", "action": action,
                })

    def test_rotated_cookie_closes_existing_connection(self) -> None:
        socket = _FakeSocket(
            [_text_frame({"version": 1, "type": "ping", "nonce": "n1"})]
        )
        socket.service.invalidate_after_first = True
        _run_immediate(room_websocket(socket))
        self.assertEqual(socket.closed, [1008])
        self.assertEqual([item["type"] for item in socket.sent], ["snapshot"])

    def test_websocket_authentication_reads_session_without_rotating_it(self) -> None:
        credential = "a" * 43
        room = _room()
        session = GuestSession(
            credential_hash=credential_digest(credential),
            room_code=room.room_code,
            player_id="player-1",
            expires_at=NOW + timedelta(minutes=30),
        )

        class Repository:
            async def load_session(self, digest: str) -> GuestSession | None:
                return session if digest == session.credential_hash else None

            async def load_room(self, code: str) -> StoredRoom | None:
                return StoredRoom(room, b"stored") if code == room.room_code else None

            async def compare_and_swap(self, *args: object, **kwargs: object) -> None:
                raise AssertionError("WebSocket authentication must not rotate the cookie.")

        service = RoomService(Repository(), clock=lambda: NOW + timedelta(minutes=1))
        result: list[AuthenticatedGuest] = []

        async def authenticate() -> None:
            result.append(await service.authenticate_player(credential))

        _run_immediate(authenticate())
        self.assertEqual(result[0].player_id, "player-1")
        self.assertEqual(result[0].state, room)
