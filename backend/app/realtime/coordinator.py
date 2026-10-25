"""Single-process room command ordering with atomic Redis state and receipts."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from math import isfinite
from uuid import uuid4

from app.api.websocket_schemas import (
    ClientCommand, ServerAcknowledgment, ServerError, ServerEvent,
)
from app.game.commands import (
    CallEmergencyMeeting, CastCategoryVote, CastPlayerVote, EndRoom, FinalizeSolution,
    LeaveRoom, RequestOfficialTestRun, RequestRematch, SendChatMessage,
    SetReady, StartMatch, StartNextRound,
)
from app.game.idempotency import command_fingerprint, durable_receipt_is_live
from app.game.models import DeadlineKind, GamePhase, OfficialRunStatus
from app.game.outcomes import TransitionAccepted
from app.game.randomness import ChoiceSource, SecureChoiceSource
from app.game.transitions import (
    apply_command, process_deadline, record_source_revision,
    record_official_run_status, start_coding_round,
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
    make_next_round,
    make_phase_deadline,
    resolve_match_setup,
)
from app.realtime.snapshots import project_event
from app.runner.service import RunnerQueueFull, RunnerService, RunnerUnavailable


def _game_command(message: ClientCommand, player_id: str):
    action = message.action
    common = {"request_id": message.request_id, "player_id": player_id}
    match action.name:
        case "set_ready": return SetReady(**common, ready=action.ready)
        case "start_match": return StartMatch(**common)
        case "start_next_round": return StartNextRound(**common)
        case "cast_category_vote": return CastCategoryVote(**common, category_id=action.category_id)
        case "call_emergency_meeting": return CallEmergencyMeeting(**common)
        case "cast_player_vote": return CastPlayerVote(**common, target_player_id=action.target_player_id)
        case "request_official_test_run": return RequestOfficialTestRun(**common, source_revision_id=action.source_revision_id)
        case "finalize_solution": return FinalizeSolution(**common, source_revision_id=action.source_revision_id)
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
        runner_service: RunnerService | None = None,
        automatic_test_debounce_seconds: float = 1.0,
    ) -> None:
        if (
            isinstance(automatic_test_debounce_seconds, bool)
            or not isinstance(automatic_test_debounce_seconds, (int, float))
            or not isfinite(automatic_test_debounce_seconds)
            or automatic_test_debounce_seconds < 0
        ):
            raise ValueError("Automatic test debounce must be a finite non-negative number.")
        self._repository = repository
        self._connections = connections
        self._choices = choice_source or SecureChoiceSource()
        self._setup_policy = setup_policy or MatchSetupPolicy()
        self._runner_service = runner_service
        self._automatic_test_debounce_seconds = automatic_test_debounce_seconds
        self._locks: dict[str, asyncio.Lock] = {}
        self._automatic_test_tasks: dict[str, asyncio.Task[None]] = {}

    @property
    def room_locks(self) -> dict[str, asyncio.Lock]:
        """Expose the single-writer lock map to other in-process room workers."""

        return self._locks

    async def close(self) -> None:
        """Cancel pending process-local debounce timers during API shutdown."""

        tasks = tuple(self._automatic_test_tasks.values())
        self._automatic_test_tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

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

            # Explicit leave remains on the HTTP/session-revocation path. A
            # transport drop is not a leave; meetings are now live commands.
            unavailable = isinstance(command, LeaveRoom)
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
                elif isinstance(command, CallEmergencyMeeting):
                    outcome = apply_command(
                        stored.state,
                        command,
                        now,
                        next_deadline=make_phase_deadline(
                            DeadlineKind.MEETING_DISCUSSION,
                            now,
                            self._setup_policy.meeting_discussion_seconds,
                        ),
                        meeting_cooldown_until=now + timedelta(
                            seconds=self._setup_policy.meeting_cooldown_seconds
                        ),
                    )
                elif isinstance(command, StartNextRound):
                    try:
                        next_round = make_next_round(
                            stored.state,
                            now,
                            self._setup_policy,
                            choices=self._choices,
                        )
                    except ValueError:
                        next_round = None
                    outcome = apply_command(
                        stored.state, command, now, next_round=next_round
                    )
                else:
                    outcome = apply_command(stored.state, command, now)
                if (
                    isinstance(command, RequestOfficialTestRun)
                    and isinstance(outcome, TransitionAccepted)
                ):
                    if self._runner_service is None:
                        outcome = None
                        result = ServerError(
                            code="RUNNER_UNAVAILABLE",
                            message="Official tests are not available right now.",
                            request_id=message.request_id,
                        )
                    else:
                        try:
                            enqueue_receipt = await self._runner_service.enqueue_for_request(
                                stored, command, now
                            )
                            current = (
                                stored.state.match.current_round
                                if stored.state.match is not None
                                else None
                            )
                            if current is not None and enqueue_receipt.run_id is not None:
                                queued = record_official_run_status(
                                    outcome.state,
                                    round_number=current.number,
                                    run_id=enqueue_receipt.run_id,
                                    source_revision_id=command.source_revision_id,
                                    status=OfficialRunStatus.QUEUED,
                                    now=now,
                                    requested_by_player_id=player_id,
                                    requested_at=now,
                                    request_id=command.request_id,
                                )
                                if isinstance(queued, TransitionAccepted):
                                    outcome = TransitionAccepted(
                                        state=queued.state,
                                        events=(*outcome.events, *queued.events),
                                    )
                        except RunnerQueueFull:
                            outcome = None
                            result = ServerError(
                                code="RUNNER_QUEUE_FULL",
                                message="The official test queue is busy; please try again.",
                                request_id=message.request_id,
                            )
                        except RunnerUnavailable:
                            outcome = None
                            result = ServerError(
                                code="RUNNER_UNAVAILABLE",
                                message="Official tests are unavailable; please try again.",
                                request_id=message.request_id,
                            )
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
                elif outcome is not None:
                    updated = stored.state
                    events = ()
                    result = ServerError(code=outcome.code.value, message=outcome.message, request_id=message.request_id)
                else:
                    updated = stored.state
                    events = ()

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

    async def resolve_game_deadline(
        self, room_code: str, deadline_id: str
    ) -> DeadlineAttempt:
        """Resolve one persisted game deadline; stale callbacks do nothing."""

        lock = self._locks.setdefault(room_code, asyncio.Lock())
        async with lock:
            for _ in range(8):
                stored = await self._repository.load_room(room_code)
                now = datetime.now(timezone.utc)
                if stored is None or stored.state.is_closed or now >= stored.state.expires_at:
                    return DeadlineAttempt.STALE
                deadline = stored.state.phase_deadline
                if (deadline is None or deadline.deadline_id != deadline_id
                    or stored.state.phase not in {
                        GamePhase.CATEGORY_VOTE,
                        GamePhase.ROLE_REVEAL,
                        GamePhase.CODING_ROUND,
                        GamePhase.MEETING_DISCUSSION,
                        GamePhase.PLAYER_VOTE,
                    }
                    or deadline.kind not in {
                        DeadlineKind.CATEGORY_VOTE,
                        DeadlineKind.ROLE_REVEAL,
                        DeadlineKind.CODING_ROUND,
                        DeadlineKind.MEETING_DISCUSSION,
                        DeadlineKind.PLAYER_VOTE,
                    }):
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
                elif deadline.kind is DeadlineKind.MEETING_DISCUSSION:
                    outcome = process_deadline(
                        stored.state,
                        deadline_id,
                        now,
                        next_deadline=make_phase_deadline(
                            DeadlineKind.PLAYER_VOTE,
                            now,
                            self._setup_policy.player_vote_seconds,
                        ),
                    )
                else:
                    outcome = process_deadline(stored.state, deadline_id, now)
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

    async def resolve_category_deadline(
        self, room_code: str, deadline_id: str
    ) -> DeadlineAttempt:
        """Compatibility wrapper retained for earlier deadline-worker callers."""

        return await self.resolve_game_deadline(room_code, deadline_id)

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
                self._schedule_automatic_test(
                    room_code, document_id, player_id, revision_id
                )
                return revision_id
        return None

    def _schedule_automatic_test(
        self, room_code: str, document_id: str, player_id: str, revision_id: str
    ) -> None:
        """Debounce saved edits; revision-level Redis dedupe also coalesces manual runs."""

        if self._runner_service is None:
            return
        prior = self._automatic_test_tasks.pop(document_id, None)
        if prior is not None:
            prior.cancel()
        task = asyncio.create_task(
            self._enqueue_automatic_test(room_code, document_id, player_id, revision_id),
            name=f"auto-test-{room_code}-{revision_id}",
        )
        self._automatic_test_tasks[document_id] = task

    async def _enqueue_automatic_test(
        self, room_code: str, document_id: str, player_id: str, revision_id: str
    ) -> None:
        """Queue a quiet-period revision if it is still the live round's code."""

        try:
            await asyncio.sleep(self._automatic_test_debounce_seconds)
            lock = self._locks.setdefault(room_code, asyncio.Lock())
            async with lock:
                if self._runner_service is None:
                    return
                stored = await self._repository.load_room(room_code)
                if stored is None or editor_document_id(stored.state) != document_id:
                    return
                match = stored.state.match
                current = match.current_round if match is not None else None
                if (
                    stored.state.phase is not GamePhase.CODING_ROUND
                    or current is None
                    or current.current_source_revision_id != revision_id
                ):
                    return
                now = datetime.now(timezone.utc)
                try:
                    receipt = await self._runner_service.enqueue_for_revision(
                        stored,
                        player_id=player_id,
                        request_id=f"auto-{uuid4().hex}",
                        source_revision_id=revision_id,
                        now=now,
                    )
                except (RunnerQueueFull, RunnerUnavailable):
                    return
                if receipt.run_id is None:
                    return
                status = record_official_run_status(
                    stored.state,
                    round_number=current.number,
                    run_id=receipt.run_id,
                    source_revision_id=revision_id,
                    status=OfficialRunStatus.QUEUED,
                    now=now,
                    requested_by_player_id=player_id,
                    requested_at=now,
                    request_id=f"auto-{uuid4().hex}",
                )
                if not isinstance(status, TransitionAccepted) or status.state == stored.state:
                    return
                sequence = stored.sequence + 1
                projected = tuple(
                    project_event(event, sequence) for event in status.events
                )
                if not await self._repository.compare_and_swap(
                    stored, status.state, advance_sequence=bool(status.events)
                ):
                    # A competing edit or manual request will either schedule
                    # the current revision again or already own this run ID.
                    return
                await self._publish(room_code, projected)
        except asyncio.CancelledError:
            raise
        finally:
            current_task = asyncio.current_task()
            if self._automatic_test_tasks.get(document_id) is current_task:
                self._automatic_test_tasks.pop(document_id, None)

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
