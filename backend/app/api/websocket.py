"""Authenticated WebSocket gateway for one guest's room."""

from __future__ import annotations

import asyncio
from collections import deque
import json
import logging
from time import monotonic

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.api.rooms import COOKIE_NAME
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
from app.realtime.auth import authenticate_socket
from app.realtime.connection_manager import RoomConnection, RoomConnectionManager
from app.realtime.snapshots import room_snapshot


router = APIRouter(prefix="/api/rooms", tags=["rooms"])
logger = logging.getLogger(__name__)
IDLE_TIMEOUT_SECONDS = 90
RATE_WINDOW_SECONDS = 10
MAX_MESSAGES_PER_WINDOW = 40
MAX_INVALID_MESSAGES = 3


def _unique_object_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON key.")
        value[key] = item
    return value


async def _send(connection: RoomConnection, message: ServerSnapshot | ServerPong | ServerError | ServerAcknowledgment) -> None:
    await connection.send(message.model_dump(mode="json"))


async def _snapshot(
    connection: RoomConnection, guest: AuthenticatedGuest, request_id: str | None = None
) -> None:
    await _send(connection, room_snapshot(guest.state, guest.player_id, guest.sequence, request_id))


async def _deny(socket: WebSocket) -> None:
    # Starlette returns an HTTP 403 when a socket is closed before accept().
    await socket.close(code=1008)


@router.websocket("/ws")
async def room_websocket(socket: WebSocket) -> None:
    guest = await authenticate_socket(socket)
    if guest is None:
        await _deny(socket)
        return
    credential = socket.cookies.get(COOKIE_NAME)

    await socket.accept()
    manager: RoomConnectionManager = socket.app.state.room_connection_manager
    connection = None
    invalid_messages = 0
    received_at: deque[float] = deque()
    try:
        coordinator = getattr(socket.app.state, "room_coordinator", None)
        if coordinator is not None:
            try:
                if not await coordinator.restore_connection(guest.state.room_code, guest.player_id):
                    await socket.close(code=1008, reason="Reconnect grace has expired.")
                    return
                guest = await socket.app.state.room_service.authenticate_player(credential)
            except RoomServiceError:
                await socket.close(code=1008, reason="Session is no longer valid.")
                return
            except RoomStorageError:
                await socket.close(code=1013, reason="Room storage is unavailable.")
                return
        connection = manager.register(guest.state.room_code, guest.player_id, socket, credential, ready=False)
        await _snapshot(connection, guest)
        if manager.activate(connection) > guest.sequence:
            try:
                guest = await socket.app.state.room_service.authenticate_player(credential)
                await _snapshot(connection, guest)
            except RoomServiceError:
                await socket.close(code=1008, reason="Session is no longer valid.")
                return
            except RoomStorageError:
                await socket.close(code=1013, reason="Room storage is unavailable.")
                return
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
                        connection,
                        ServerError(code="UNSUPPORTED_VERSION", message="Unsupported protocol version."),
                    )
                    await socket.close(code=1002)
                    return
                message = client_message_adapter.validate_python(payload)
            except (ValueError, ValidationError, TypeError, RecursionError):
                invalid_messages += 1
                await _send(
                    connection,
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
                    connection,
                    ServerError(code="STORAGE_UNAVAILABLE", message="Room storage is unavailable."),
                )
                await socket.close(code=1013)
                return

            if isinstance(message, ClientPing):
                await _send(connection, ServerPong(nonce=message.nonce))
            elif isinstance(message, ClientSnapshotRequest):
                await _snapshot(connection, guest, request_id=message.request_id)
            elif isinstance(message, ClientCommand):
                coordinator = getattr(
                    socket.app.state, "room_coordinator", None
                )
                if coordinator is None:
                    await _send(
                        connection,
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
                        connection,
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
                await _send(connection, result)
    except WebSocketDisconnect:
        pass
    finally:
        if connection is not None:
            manager.unregister(connection)
            coordinator = getattr(socket.app.state, "room_coordinator", None)
            if coordinator is not None and not manager.has_connections(connection.room_code, connection.player_id):
                try:
                    await coordinator.mark_disconnected(connection.room_code, connection.player_id)
                except RoomStorageError:
                    # The stored player still has their credential. Startup recovery
                    # handles process loss; a later reconnect can restore presence.
                    logger.warning("Could not record a room disconnect while storage was unavailable.")
