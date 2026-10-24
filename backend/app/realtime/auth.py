"""WebSocket handshake authorization, based on the existing guest session."""

from fastapi import WebSocket

from app.api.rooms import COOKIE_NAME
from app.rooms.repository import RoomStorageError
from app.rooms.service import AuthenticatedGuest, RoomServiceError


async def authenticate_socket(socket: WebSocket) -> AuthenticatedGuest | None:
    origin = socket.headers.get("origin")
    if origin is None or origin not in socket.app.state.allowed_origins:
        return None
    if socket.url.query:
        return None
    try:
        return await socket.app.state.room_service.authenticate_player(
            socket.cookies.get(COOKIE_NAME)
        )
    except (RoomServiceError, RoomStorageError):
        return None
