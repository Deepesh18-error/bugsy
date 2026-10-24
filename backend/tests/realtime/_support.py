"""Small synchronous fakes for the WebSocket boundary tests."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from app.api.websocket import RoomConnectionManager
from app.game.models import PlayerState, RoomState
from app.rooms.repository import CommandReceipt, StoredRoom
from app.rooms.service import AuthenticatedGuest, RoomServiceError


NOW = datetime.now(timezone.utc)
DISCONNECT = {"type": "websocket.disconnect", "code": 1000}


def make_room() -> RoomState:
    return RoomState(
        room_code="ABCDEFG2",
        host_player_id="player-1",
        players=(
            PlayerState(player_id="player-1", display_name="Ada", joined_at=NOW),
            PlayerState(player_id="player-2", display_name="Ben", joined_at=NOW),
        ),
        created_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )


def text_frame(payload: dict[str, object]) -> dict[str, object]:
    return {"type": "websocket.receive", "text": json.dumps(payload), "bytes": None}


def raw_frame(payload: str) -> dict[str, object]:
    return {"type": "websocket.receive", "text": payload, "bytes": None}


class FakeService:
    def __init__(self, room: RoomState | None = None, player_id: str = "player-2") -> None:
        self.guest = AuthenticatedGuest(room or make_room(), player_id, NOW + timedelta(hours=1))
        self.calls = 0

    async def authenticate_player(self, credential: str | None) -> AuthenticatedGuest:
        self.calls += 1
        if credential != "private-cookie":
            raise RoomServiceError("SESSION_INVALID", "Invalid session.", 401)
        return self.guest


class FakeSocket:
    def __init__(
        self,
        frames: list[dict[str, object]],
        *,
        service: object | None = None,
        origin: str = "http://127.0.0.1:5173",
        credential: str | None = "private-cookie",
    ) -> None:
        self.headers = {"origin": origin}
        self.url = SimpleNamespace(query="")
        self.cookies = {} if credential is None else {"codemafia_guest": credential}
        self.manager = RoomConnectionManager()
        self.service = service or FakeService()
        self.app = SimpleNamespace(state=SimpleNamespace(
            allowed_origins=("http://127.0.0.1:5173",),
            room_service=self.service,
            room_connection_manager=self.manager,
            room_coordinator=None,
        ))
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


async def _immediate_wait(awaitable: object, *, timeout: float) -> object:
    return await awaitable


def run_socket(coroutine: object) -> None:
    """Run immediate fake I/O without opening an event-loop socket on Windows."""
    with patch("app.api.websocket.asyncio.wait_for", _immediate_wait):
        try:
            coroutine.send(None)
        except StopIteration:
            return
        raise AssertionError("The fake WebSocket unexpectedly yielded.")


class FakeRepository:
    def __init__(self, room: RoomState | None = None) -> None:
        self.stored = StoredRoom(room or make_room(), b"revision-0")
        self.receipts: dict[tuple[str, str, str], CommandReceipt] = {}
        self.commits = 0

    async def load_room(self, room_code: str) -> StoredRoom | None:
        return self.stored if room_code == self.stored.state.room_code else None

    async def load_command_receipt(
        self, room_code: str, player_id: str, request_id: str
    ) -> CommandReceipt | None:
        return self.receipts.get((room_code, player_id, request_id))

    async def compare_and_swap(
        self, previous: StoredRoom, updated: RoomState, *,
        receipt: CommandReceipt | None = None, advance_sequence: bool = False,
        **_: object,
    ) -> bool:
        if previous.raw != self.stored.raw:
            return False
        self.commits += 1
        sequence = previous.sequence + int(advance_sequence)
        if receipt is not None:
            self.receipts[(previous.state.room_code, receipt.player_id, receipt.request_id)] = receipt
        self.stored = replace(
            previous, state=updated, sequence=sequence,
            raw=f"revision-{self.commits}".encode(),
        )
        return True
