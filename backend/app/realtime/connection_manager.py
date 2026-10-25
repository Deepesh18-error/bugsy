"""Process-local room sockets. Only safe projected envelopes may be sent."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from fastapi import WebSocket, WebSocketDisconnect

from app.api.websocket_schemas import ServerEvent
from app.rooms.repository import RoomStorageError
from app.rooms.service import AuthenticatedGuest, RoomServiceError


@dataclass(eq=False, slots=True)
class RoomConnection:
    socket: WebSocket
    room_code: str
    player_id: str
    credential: str | None = None
    ready: bool = True
    pending_sequence: int = -1
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def send(self, payload: dict[str, object]) -> None:
        async with self.send_lock:
            await self.socket.send_json(payload)


class RoomConnectionManager:
    def __init__(
        self,
        authenticate: Callable[[str | None], Awaitable[AuthenticatedGuest]] | None = None,
    ) -> None:
        self._connections: dict[str, dict[str, set[RoomConnection]]] = {}
        self._authenticate = authenticate

    def register(self, room_code: str, player_id: str, socket: WebSocket, credential: str | None = None,
                 *, ready: bool = True) -> RoomConnection:
        connection = RoomConnection(socket, room_code, player_id, credential, ready=ready)
        self._connections.setdefault(room_code, {}).setdefault(player_id, set()).add(connection)
        return connection

    def unregister(self, connection: RoomConnection) -> None:
        room = self._connections.get(connection.room_code)
        if room is None:
            return
        sockets = room.get(connection.player_id)
        if sockets is not None:
            sockets.discard(connection)
            if not sockets:
                del room[connection.player_id]
        if not room:
            del self._connections[connection.room_code]

    def has_connections(self, room_code: str, player_id: str) -> bool:
        return bool(self._connections.get(room_code, {}).get(player_id))

    def activate(self, connection: RoomConnection) -> int:
        """Enable events after the first authorized snapshot is sent."""

        connection.ready = True
        return connection.pending_sequence

    async def _deliver(self, recipients: tuple[RoomConnection, ...], event: ServerEvent) -> None:
        payload = event.model_dump(mode="json")
        for connection in recipients:
            try:
                if not connection.ready:
                    connection.pending_sequence = max(connection.pending_sequence, event.sequence)
                    continue
                if self._authenticate is not None:
                    guest = await self._authenticate(connection.credential)
                    if guest.state.room_code != connection.room_code or guest.player_id != connection.player_id:
                        self.unregister(connection)
                        continue
                await asyncio.wait_for(connection.send(payload), timeout=3)
            except RoomStorageError:
                # A temporary Redis outage does not mean this socket or guest
                # has departed. The next snapshot recovers missed events.
                continue
            except (asyncio.TimeoutError, RuntimeError, OSError, WebSocketDisconnect, RoomServiceError):
                self.unregister(connection)

    async def broadcast(self, room_code: str, event: ServerEvent) -> None:
        room = self._connections.get(room_code, {})
        await self._deliver(tuple(item for sockets in room.values() for item in sockets), event)

    async def send_private(self, room_code: str, player_id: str, event: ServerEvent) -> None:
        recipients = tuple(self._connections.get(room_code, {}).get(player_id, ()))
        await self._deliver(recipients, event)

    async def close_all(self) -> None:
        connections = tuple(
            item for room in self._connections.values() for sockets in room.values() for item in sockets
        )
        for item in connections:
            try:
                await item.socket.close(code=1001)
            except (RuntimeError, OSError, WebSocketDisconnect):
                pass
        self._connections.clear()
