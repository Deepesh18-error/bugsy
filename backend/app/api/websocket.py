"""Authenticated WebSocket gateway for one guest's room.

This increment supports an authorized snapshot and application heartbeat.
Commands are parsed but fail closed until the room coordinator is installed;
the gateway must never acknowledge a game action before durable persistence.
"""

from __future__ import annotations

import asyncio
from collections import deque
import json
from time import monotonic
from typing import Protocol

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.api.rooms import COOKIE_NAME
from app.api.schemas import build_room_response
from app.api.websocket_schemas import (
    MAX_MESSAGE_BYTES,
    PROTOCOL_VERSION,
    ClientCommand,
    ClientPing,
    ClientSnapshotRequest,
    ServerAcknowledgment,
    ServerError,
    ServerPong,
    ServerSnapshot,
    client_message_adapter,
)
from app.rooms.repository import RoomStorageError
from app.rooms.service import AuthenticatedGuest, RoomServiceError


router = APIRouter(prefix="/api/rooms", tags=["rooms"])
IDLE_TIMEOUT_SECONDS = 90
RATE_WINDOW_SECONDS = 10
MAX_MESSAGES_PER_WINDOW = 40
MAX_INVALID_MESSAGES = 3


class RoomCommandCoordinator(Protocol):
    """The later command coordinator must persist before returning an ack."""

    async def dispatch(
        self, guest: AuthenticatedGuest, command: ClientCommand
    ) -> ServerAcknowledgment | ServerError: ...


class RoomConnectionManager:
    """Track sockets in this one API process for later room event delivery."""

    def __init__(self) -> None:
        self._connections: dict[str, dict[str, set[WebSocket]]] = {}

    def register(self, room_code: str, player_id: str, socket: WebSocket) -> None:
        self._connections.setdefault(room_code, {}).setdefault(player_id, set()).add(socket)

    def unregister(self, room_code: str, player_id: str, socket: WebSocket) -> None:
        room = self._connections.get(room_code)
        if room is None:
            return
        sockets = room.get(player_id)
        if sockets is not None:
            sockets.discard(socket)
            if not sockets:
                del room[player_id]
        if not room:
            del self._connections[room_code]

    async def close_all(self) -> None:
        sockets = {
            socket
            for room in self._connections.values()
            for player_sockets in room.values()
            for socket in player_sockets
        }
        for socket in sockets:
            try:
                await socket.close(code=1001)
            except (RuntimeError, OSError, WebSocketDisconnect):
                pass
        self._connections.clear()


def _unique_object_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON key.")
        value[key] = item
    return value


async def _send(socket: WebSocket, message: ServerSnapshot | ServerPong | ServerError | ServerAcknowledgment) -> None:
    await socket.send_json(message.model_dump(mode="json"))


async def _snapshot(
    socket: WebSocket, guest: AuthenticatedGuest, request_id: str | None = None
) -> None:
    await _send(
        socket,
        ServerSnapshot(
            sequence=None,
            request_id=request_id,
            room=build_room_response(guest.state, guest.player_id).room,
        ),
    )


async def _deny(socket: WebSocket) -> None:
    # Starlette returns an HTTP 403 when a socket is closed before accept().
    await socket.close(code=1008)


@router.websocket("/ws")
async def room_websocket(socket: WebSocket) -> None:
    origin = socket.headers.get("origin")
    if origin is None or origin not in socket.app.state.allowed_origins:
        await _deny(socket)
        return
    # Credentials and room identity belong in the HttpOnly cookie, never a URL.
    if socket.url.query:
        await _deny(socket)
        return

    credential = socket.cookies.get(COOKIE_NAME)
    try:
        guest = await socket.app.state.room_service.authenticate_player(credential)
    except (RoomServiceError, RoomStorageError):
        await _deny(socket)
        return

    await socket.accept()
    manager: RoomConnectionManager = socket.app.state.room_connection_manager
    manager.register(guest.state.room_code, guest.player_id, socket)
    invalid_messages = 0
    received_at: deque[float] = deque()
    try:
        await _snapshot(socket, guest)
        while True:
            try:
                frame = await asyncio.wait_for(
                    socket.receive(), timeout=IDLE_TIMEOUT_SECONDS
                )
            except asyncio.TimeoutError:
                await socket.close(code=1001, reason="Connection idle timeout.")
                return
            if frame["type"] == "websocket.disconnect":
                return
            if frame.get("bytes") is not None or frame.get("text") is None:
                await socket.close(code=1003, reason="Text messages are required.")
                return
            raw = frame["text"]
            if len(raw.encode("utf-8")) > MAX_MESSAGE_BYTES:
                await socket.close(code=1009, reason="Message is too large.")
                return

            now = monotonic()
            while received_at and now - received_at[0] >= RATE_WINDOW_SECONDS:
                received_at.popleft()
            received_at.append(now)
            if len(received_at) > MAX_MESSAGES_PER_WINDOW:
                await socket.close(code=1008, reason="Message rate exceeded.")
                return

            try:
                payload = json.loads(raw, object_pairs_hook=_unique_object_keys)
                if isinstance(payload, dict) and payload.get("version") != PROTOCOL_VERSION:
                    await _send(
                        socket,
                        ServerError(code="UNSUPPORTED_VERSION", message="Unsupported protocol version."),
                    )
                    await socket.close(code=1002)
                    return
                message = client_message_adapter.validate_python(payload)
            except (ValueError, ValidationError, TypeError, RecursionError):
                invalid_messages += 1
                await _send(
                    socket,
                    ServerError(code="INVALID_MESSAGE", message="Invalid WebSocket message."),
                )
                if invalid_messages >= MAX_INVALID_MESSAGES:
                    await socket.close(code=1008, reason="Too many invalid messages.")
                    return
                continue

            # HTTP resume or leave may revoke this cookie while the socket is
            # open. Recheck it before every read or command from the guest.
            try:
                guest = await socket.app.state.room_service.authenticate_player(credential)
            except RoomServiceError:
                await socket.close(code=1008, reason="Session is no longer valid.")
                return
            except RoomStorageError:
                await _send(
                    socket,
                    ServerError(code="STORAGE_UNAVAILABLE", message="Room storage is unavailable."),
                )
                await socket.close(code=1013)
                return

            if isinstance(message, ClientPing):
                await _send(socket, ServerPong(nonce=message.nonce))
            elif isinstance(message, ClientSnapshotRequest):
                await _snapshot(socket, guest, request_id=message.request_id)
            elif isinstance(message, ClientCommand):
                coordinator: RoomCommandCoordinator | None = getattr(
                    socket.app.state, "room_coordinator", None
                )
                if coordinator is None:
                    await _send(
                        socket,
                        ServerError(
                            code="COMMANDS_UNAVAILABLE",
                            message="Live game commands are not available yet.",
                            request_id=message.request_id,
                        ),
                    )
                    continue
                # Only the coordinator may acknowledge accepted game commands.
                # It must bind player_id to guest and persist before returning.
                try:
                    result = await coordinator.dispatch(guest, message)
                except RoomStorageError:
                    await _send(
                        socket,
                        ServerError(
                            code="STORAGE_UNAVAILABLE",
                            message="Room storage is unavailable.",
                            request_id=message.request_id,
                        ),
                    )
                    await socket.close(code=1013)
                    return
                if not isinstance(result, (ServerAcknowledgment, ServerError)):
                    await socket.close(code=1011, reason="Invalid coordinator response.")
                    return
                await _send(socket, result)
    except WebSocketDisconnect:
        pass
    finally:
        manager.unregister(guest.state.room_code, guest.player_id, socket)
