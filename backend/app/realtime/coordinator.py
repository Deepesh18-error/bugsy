"""Single-process room command ordering with atomic Redis state and receipts."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from hashlib import sha256
import json

from app.api.websocket_schemas import ClientCommand, ServerAcknowledgment, ServerError
from app.game.commands import (
    CallEmergencyMeeting, CastCategoryVote, CastPlayerVote, EndRoom,
    LeaveRoom, RequestOfficialTestRun, RequestRematch, SendChatMessage,
    SetReady, StartMatch,
)
from app.game.outcomes import TransitionAccepted
from app.game.transitions import apply_command
from app.rooms.repository import CommandReceipt, RoomRepository
from app.rooms.service import AuthenticatedGuest
from app.realtime.connection_manager import RoomConnectionManager
from app.realtime.snapshots import project_event


def _game_command(message: ClientCommand, player_id: str):
    action = message.action
    common = {"request_id": message.request_id, "player_id": player_id}
    match action.name:
        case "set_ready": return SetReady(**common, ready=action.ready)
        case "start_match": return StartMatch(**common)
        case "cast_category_vote": return CastCategoryVote(**common, category_id=action.category_id)
        case "call_emergency_meeting": return CallEmergencyMeeting(**common)
        case "cast_player_vote": return CastPlayerVote(**common, target_player_id=action.target_player_id)
        case "request_official_test_run": return RequestOfficialTestRun(**common, source_revision_id=action.source_revision_id)
        case "send_chat_message": return SendChatMessage(**common, message=action.message)
        case "leave_room": return LeaveRoom(**common)
        case "end_room": return EndRoom(**common)
        case "request_rematch": return RequestRematch(**common)
        case _: raise ValueError("Unsupported command action.")


def _fingerprint(message: ClientCommand) -> str:
    raw = json.dumps(message.action.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return sha256(raw.encode("utf-8")).hexdigest()


class RoomCoordinator:
    def __init__(self, repository: RoomRepository, connections: RoomConnectionManager) -> None:
        self._repository = repository
        self._connections = connections
        self._locks: dict[str, asyncio.Lock] = {}

    async def dispatch(self, guest: AuthenticatedGuest, message: ClientCommand) -> ServerAcknowledgment | ServerError:
        room_code = guest.state.room_code
        lock = self._locks.setdefault(room_code, asyncio.Lock())
        async with lock:
            return await self._dispatch_locked(room_code, guest.player_id, message)

    async def _dispatch_locked(self, room_code: str, player_id: str, message: ClientCommand) -> ServerAcknowledgment | ServerError:
        fingerprint = _fingerprint(message)
        for _ in range(8):
            stored = await self._repository.load_room(room_code)
            now = datetime.now(timezone.utc)
            if stored is None or stored.state.is_closed or now >= stored.state.expires_at:
                return ServerError(code="ROOM_UNAVAILABLE", message="Room is unavailable.", request_id=message.request_id)
            if not any(player.player_id == player_id and player.connection.value != "departed" for player in stored.state.players):
                return ServerError(code="SESSION_INVALID", message="Guest session is invalid.", request_id=message.request_id)
            for item in stored.receipts:
                if item.player_id == player_id and item.request_id == message.request_id:
                    if item.fingerprint != fingerprint:
                        return ServerError(code="DUPLICATE_REQUEST", message="Request ID was used for a different action.", request_id=message.request_id)
                    if item.accepted:
                        return ServerAcknowledgment(request_id=message.request_id, sequence=item.sequence)
                    return ServerError(code=item.code or "COMMAND_REJECTED", message=item.message or "Command rejected.", request_id=message.request_id)

            command = _game_command(message, player_id)
            # These actions require a durable scheduler, collaborative editor,
            # or credential revocation that has not been connected yet.
            unavailable = isinstance(command, (StartMatch, CallEmergencyMeeting, RequestOfficialTestRun, LeaveRoom))
            if unavailable:
                result: ServerAcknowledgment | ServerError = ServerError(
                    code="COMMAND_UNAVAILABLE",
                    message="This game action is not available yet.",
                    request_id=message.request_id,
                )
                updated = stored.state
                events = ()
            else:
                outcome = apply_command(stored.state, command, now)
                if isinstance(outcome, TransitionAccepted):
                    updated = outcome.state
                    events = outcome.events
                    result = ServerAcknowledgment(
                        request_id=message.request_id,
                        sequence=stored.sequence + (1 if updated != stored.state or events else 0),
                    )
                else:
                    updated = stored.state
                    events = ()
                    result = ServerError(code=outcome.code.value, message=outcome.message, request_id=message.request_id)

            sequence = result.sequence if isinstance(result, ServerAcknowledgment) else stored.sequence
            # Validate every event projection before committing an irreversible
            # state update. New private event types must be explicitly mapped.
            projected = tuple(project_event(event, sequence) for event in events)
            receipt = CommandReceipt(
                player_id=player_id, request_id=message.request_id,
                fingerprint=fingerprint, sequence=sequence,
                accepted=isinstance(result, ServerAcknowledgment),
                code=result.code if isinstance(result, ServerError) else None,
                message=result.message if isinstance(result, ServerError) else None,
                recorded_at=now,
            )
            if not await self._repository.compare_and_swap(
                stored, updated, receipt=receipt, advance_sequence=bool(events)
            ):
                continue
            # Persistence is complete before any event or acknowledgment.
            for recipient, event in projected:
                if recipient is None:
                    await self._connections.broadcast(room_code, event)
                else:
                    await self._connections.send_private(room_code, recipient, event)
            return result
        return ServerError(code="ROOM_BUSY", message="Room changed; please retry.", request_id=message.request_id)
