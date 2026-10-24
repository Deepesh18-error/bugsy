"""The handshake checks origin and the current guest credential before accept."""

from datetime import timedelta
import unittest

from app.api.websocket import room_websocket
from app.rooms.identity import credential_digest
from app.rooms.repository import GuestSession, StoredRoom
from app.rooms.service import RoomService
from _support import DISCONNECT, NOW, FakeSocket, make_room, run_socket


CREDENTIAL = "a" * 43


class SessionRepository:
    def __init__(self, *, expired: bool = False) -> None:
        self.room = make_room()
        self.session = GuestSession(
            credential_hash=credential_digest(CREDENTIAL),
            room_code=self.room.room_code,
            player_id="player-2",
            expires_at=NOW - timedelta(seconds=1) if expired else NOW + timedelta(minutes=30),
        )
        self.lookups = 0

    async def load_session(self, credential_hash: str) -> GuestSession | None:
        self.lookups += 1
        return self.session if credential_hash == self.session.credential_hash else None

    async def load_room(self, room_code: str) -> StoredRoom | None:
        return StoredRoom(self.room, b"room") if room_code == self.room.room_code else None


class WebSocketAuthTests(unittest.TestCase):
    def make_socket(self, repository: SessionRepository, **options: object) -> FakeSocket:
        return FakeSocket(
            [DISCONNECT], service=RoomService(repository, clock=lambda: NOW),
            credential=CREDENTIAL, **options,
        )

    def test_missing_cookie_is_denied_before_accept(self) -> None:
        repository = SessionRepository()
        socket = self.make_socket(repository)
        socket.cookies.clear()
        run_socket(room_websocket(socket))
        self.assertFalse(socket.accepted)
        self.assertEqual(socket.closed, [1008])
        self.assertEqual(repository.lookups, 0)

    def test_unknown_and_expired_credentials_are_denied(self) -> None:
        for repository, cookie in ((SessionRepository(), "b" * 43), (SessionRepository(expired=True), CREDENTIAL)):
            with self.subTest(cookie=cookie, expired=repository.session.expires_at < NOW):
                socket = self.make_socket(repository)
                socket.cookies["codemafia_guest"] = cookie
                run_socket(room_websocket(socket))
                self.assertFalse(socket.accepted)
                self.assertEqual(socket.closed, [1008])

    def test_rejected_origin_is_denied_without_session_lookup(self) -> None:
        repository = SessionRepository()
        socket = self.make_socket(repository, origin="https://untrusted.example")
        run_socket(room_websocket(socket))
        self.assertFalse(socket.accepted)
        self.assertEqual(socket.closed, [1008])
        self.assertEqual(repository.lookups, 0)

    def test_valid_session_receives_only_its_authorized_snapshot(self) -> None:
        repository = SessionRepository()
        socket = self.make_socket(repository)
        run_socket(room_websocket(socket))
        self.assertTrue(socket.accepted)
        self.assertEqual(socket.sent[0]["room"]["self_player_id"], "player-2")
        self.assertNotIn(CREDENTIAL, repr(socket.sent))
