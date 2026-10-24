"""Single-process room command ordering with atomic Redis state and receipts."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from hashlib import sha256
import json
from uuid import uuid4

from app.api.websocket_schemas import (
    ClientCommand, ServerAcknowledgment, ServerError, ServerEvent,
)
from app.game.commands import (
    CallEmergencyMeeting, CastCategoryVote, CastPlayerVote, EndRoom,
    LeaveRoom, RequestOfficialTestRun, RequestRematch, SendChatMessage,
    SetReady, StartMatch,
)
from app.game.idempotency import command_fingerprint, durable_receipt_is_live
from app.game.models import DeadlineKind, GamePhase
from app.game.outcomes import TransitionAccepted
from app.game.randomness import ChoiceSource, SecureChoiceSource
from app.game.transitions import (
    apply_command, end_coding_round, record_source_revision, start_coding_round,
)
from app.rooms.repository import CommandReceipt, RoomRepository, editor_document_id
from app.rooms.service import AuthenticatedGuest
from app.realtime.connection_manager import RoomConnectionManager
from app.realtime.deadline_scheduler import DeadlineAttempt
from app.realtime.match_setup import (
    MatchSetupPolicy,
    available_categories,
    category_vote_is_complete,
    make_first_round,
    make_phase_deadline,
    resolve_match_setup,
)
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


def _legacy_wire_fingerprint(message: ClientCommand) -> str:
    """Recognize receipts written by the first, short-lived v1 coordinator."""

    raw = json.dumps(message.action.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return sha256(raw.encode("utf-8")).hexdigest()


class RoomCoordinator:
    def __init__(
        self,
        repository: RoomRepository,
        connections: RoomConnectionManager,
        *,
        choice_source: ChoiceSource | None = None,
        setup_policy: MatchSetupPolicy | None = None,
    ) -> None:
        self._repository = repository
        self._connections = connections
        self._choices = choice_source or SecureChoiceSource()
        self._setup_policy = setup_policy or MatchSetupPolicy()
        self._locks: dict[str, asyncio.Lock] = {}

    async def dispatch(self, guest: AuthenticatedGuest, message: ClientCommand) -> ServerAcknowledgment | ServerError:
        room_code = guest.state.room_code
        lock = self._locks.setdefault(room_code, asyncio.Lock())
        async with lock:
            return await self._dispatch_locked(room_code, guest.player_id, message)

    async def _dispatch_locked(self, room_code: str, player_id: str, message: ClientCommand) -> ServerAcknowledgment | ServerError:
        command = _game_command(message, player_id)
        fingerprint = command_fingerprint(command)
        legacy_fingerprint = _legacy_wire_fingerprint(message)
        for _ in range(8):
            stored = await self._repository.load_room(room_code)
            now = datetime.now(timezone.utc)
            if stored is None or stored.state.is_closed or now >= stored.state.expires_at:
                return ServerError(code="ROOM_UNAVAILABLE", message="Room is unavailable.", request_id=message.request_id)
            if not any(player.player_id == player_id and player.connection.value != "departed" for player in stored.state.players):
                return ServerError(code="SESSION_INVALID", message="Guest session is invalid.", request_id=message.request_id)
            durable_receipt = await self._repository.load_command_receipt(
                room_code, player_id, message.request_id
            )
            candidates = (
                (durable_receipt, *stored.receipts)
                if durable_receipt is not None else stored.receipts
            )
            for item in candidates:
                if (
                    item.player_id == player_id
                    and item.request_id == message.request_id
                    and (
                        item is durable_receipt
                        or durable_receipt_is_live(item.recorded_at, now)
                    )
                ):
                    if item.fingerprint not in (fingerprint, legacy_fingerprint):
                        return ServerError(code="DUPLICATE_REQUEST", message="Request ID was used for a different action.", request_id=message.request_id)
                    if item.accepted:
                        return ServerAcknowledgment(request_id=message.request_id, sequence=item.sequence)
                    return ServerError(code=item.code or "COMMAND_REJECTED", message=item.message or "Command rejected.", request_id=message.request_id)

            # Meeting timers, runner jobs, and WebSocket leave revocation are
            # connected in later phases.
            unavailable = isinstance(command, (CallEmergencyMeeting, RequestOfficialTestRun, LeaveRoom))
            if isinstance(command, StartMatch) and not available_categories(self._setup_policy):
                result = ServerError(code="CHALLENGE_UNAVAILABLE", message="No challenge is ready for a live match.", request_id=message.request_id)
                updated, events = stored.state, ()
            elif isinstance(command, CastCategoryVote) and command.category_id not in available_categories(self._setup_policy):
                result = ServerError(code="CATEGORY_UNAVAILABLE", message="That category has no live challenge yet.", request_id=message.request_id)
                updated, events = stored.state, ()
            elif unavailable:
                result: ServerAcknowledgment | ServerError = ServerError(
                    code="COMMAND_UNAVAILABLE",
                    message="This game action is not available yet.",
                    request_id=message.request_id,
                )
                updated = stored.state
                events = ()
            else:
                if isinstance(command, StartMatch):
                    outcome = apply_command(
                        stored.state,
                        command,
                        now,
                        next_deadline=make_phase_deadline(
                            DeadlineKind.CATEGORY_VOTE,
                            now,
                            self._setup_policy.category_vote_seconds,
                        ),
                    )
                else:
                    outcome = apply_command(stored.state, command, now)
                if (
                    isinstance(command, CastCategoryVote)
                    and isinstance(outcome, TransitionAccepted)
                    and category_vote_is_complete(outcome.state)
                ):
                    resolved = resolve_match_setup(
                        outcome.state,
                        now,
                        choices=self._choices,
                        policy=self._setup_policy,
                    )
                    if isinstance(resolved, TransitionAccepted):
                        outcome = TransitionAccepted(
                            state=resolved.state,
                            events=(*outcome.events, *resolved.events),
                        )
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
            await self._publish(room_code, projected)
            return result
        return ServerError(code="ROOM_BUSY", message="Room changed; please retry.", request_id=message.request_id)

    async def resolve_category_deadline(
        self, room_code: str, deadline_id: str
    ) -> DeadlineAttempt:
        """Resolve one persisted setup/coding deadline; stale callbacks do nothing."""

        lock = self._locks.setdefault(room_code, asyncio.Lock())
        async with lock:
            for _ in range(8):
                stored = await self._repository.load_room(room_code)
                now = datetime.now(timezone.utc)
                if stored is None or stored.state.is_closed or now >= stored.state.expires_at:
                    return DeadlineAttempt.STALE
                deadline = stored.state.phase_deadline
                if (deadline is None or deadline.deadline_id != deadline_id
                    or stored.state.phase not in {GamePhase.CATEGORY_VOTE, GamePhase.ROLE_REVEAL, GamePhase.CODING_ROUND}
                    or deadline.kind not in {DeadlineKind.CATEGORY_VOTE, DeadlineKind.ROLE_REVEAL, DeadlineKind.CODING_ROUND}):
                    return DeadlineAttempt.STALE
                if now < deadline.due_at:
                    return DeadlineAttempt.NOT_DUE

                if stored.state.phase is GamePhase.CATEGORY_VOTE:
                    outcome = resolve_match_setup(
                        stored.state, now, choices=self._choices, policy=self._setup_policy,
                    )
                elif stored.state.phase is GamePhase.ROLE_REVEAL:
                    try:
                        round_state = make_first_round(stored.state, now, self._setup_policy)
                    except ValueError:
                        return DeadlineAttempt.RETRY
                    outcome = start_coding_round(stored.state, round_state, now)
                else:
                    outcome = end_coding_round(stored.state, now, deadline_id=deadline_id)
                if not isinstance(outcome, TransitionAccepted):
                    # Keep the durable entry for investigation/retry; do not
                    # silently delete a vote whose transition was rejected.
                    return DeadlineAttempt.RETRY
                sequence = stored.sequence + 1
                projected = tuple(project_event(event, sequence) for event in outcome.events)
                if not await self._repository.compare_and_swap(
                    stored,
                    outcome.state,
                    advance_sequence=True,
                ):
                    continue
                await self._publish(room_code, projected)
                return DeadlineAttempt.COMMITTED
            return DeadlineAttempt.RETRY

    async def commit_editor_change(
        self, room_code: str, player_id: str, document_id: str,
        previous_revision_id: str, source: str, y_state: str,
        restored_from_revision_id: str | None = None,
    ) -> str | None:
        """Commit one trusted sync-service update before anyone sees it."""

        lock = self._locks.setdefault(room_code, asyncio.Lock())
        async with lock:
            for _ in range(8):
                stored = await self._repository.load_room(room_code)
                now = datetime.now(timezone.utc)
                if stored is None or stored.state.phase is not GamePhase.CODING_ROUND:
                    return None
                match = stored.state.match
                current = match.current_round if match else None
                if (match is None or current is None or match.match_id is None
                    or document_id != editor_document_id(stored.state)
                    or now >= current.deadline.due_at
                    or current.current_source_revision_id != previous_revision_id
                    or not any(player.player_id == player_id and player.is_alive
                               and player.connection.value == "connected"
                               for player in stored.state.players)):
                    return None
                if restored_from_revision_id is not None:
                    document = await self._repository.load_editor_document(document_id)
                    if (document is None or not any(
                        item.revision_id == restored_from_revision_id and item.source == source
                        for item in document.history
                    )):
                        return None
                revision_id = uuid4().hex
                outcome = record_source_revision(
                    stored.state, revision_id, now,
                    restored_from_revision_id=restored_from_revision_id,
                    restored_by_player_id=player_id if restored_from_revision_id else None,
                )
                if not isinstance(outcome, TransitionAccepted):
                    return None
                sequence = stored.sequence + 1
                projected = tuple(project_event(event, sequence) for event in outcome.events)
                committed = await self._repository.commit_editor_document(
                    stored, outcome.state, document_id=document_id,
                    previous_revision_id=previous_revision_id, revision_id=revision_id,
                    source=source, y_state=y_state, author_player_id=player_id,
                    recorded_at=now, restored_from_revision_id=restored_from_revision_id,
                )
                if not committed:
                    continue
                await self._publish(room_code, projected)
                return revision_id
        return None

    async def _publish(
        self,
        room_code: str,
        projected: tuple[tuple[str | None, ServerEvent], ...],
    ) -> None:
        """Send only allowlisted event projections after the room commit."""

        for recipient, event in projected:
            if recipient is None:
                await self._connections.broadcast(room_code, event)
            else:
                await self._connections.send_private(room_code, recipient, event)
