"""Authenticate runner results and commit only current, complete verdicts."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.api.websocket_schemas import ServerEvent
from app.challenges.loader import ChallengeLoadError, load_challenge
from app.game.models import GamePhase, OfficialRunStatus, OfficialTestResult
from app.game.outcomes import TransitionAccepted
from app.game.transitions import (
    record_official_run_status,
    record_official_test_result,
    record_verified_sabotage_objective,
)
from app.observability import OperationalMetrics
from app.realtime.connection_manager import RoomConnectionManager
from app.realtime.snapshots import project_event
from app.rooms.repository import RoomRepository, editor_document_id
from app.runner.sabotage_policy import attributable_regression
from app.runner.contracts import (
    RunnerJob,
    RunnerResult,
    RunnerStatus,
    verify_result_signature,
)
from app.runner.projections import player_safe_result_payload
from app.runner.repository import RunnerRepository, RunnerStorageError


class InvalidRunnerMessage(ValueError):
    """A malformed or unauthorized result is permanent and may be acknowledged."""


class RunnerResultProcessor:
    def __init__(
        self,
        rooms: RoomRepository,
        runner: RunnerRepository,
        connections: RoomConnectionManager,
        *,
        signing_key: str,
        room_locks: dict[str, asyncio.Lock] | None = None,
        metrics: OperationalMetrics | None = None,
    ) -> None:
        if len(signing_key.encode("utf-8")) < 32:
            raise ValueError("CODEMAFIA_RUNNER_RESULT_HMAC_KEY must contain at least 32 bytes.")
        self._rooms = rooms
        self._runner = runner
        self._connections = connections
        self._signing_key = signing_key
        self._locks = room_locks if room_locks is not None else {}
        self._metrics = metrics

    async def process(self, result: RunnerResult) -> bool:
        """Return True for a terminal message (including stale/invalid results)."""

        if not verify_result_signature(result, self._signing_key):
            raise InvalidRunnerMessage("Runner result signature is invalid.")
        job = await self._runner.load_job(result.run_id)
        if job is None:
            raise InvalidRunnerMessage("Runner result has no registered job.")
        _match_job(result, job)
        try:
            loaded = load_challenge(job.challenge_id, job.challenge_version)
        except ChallengeLoadError as exc:
            raise InvalidRunnerMessage("The registered challenge cannot be loaded.") from exc
        if loaded.content_digest != job.challenge_content_digest:
            raise InvalidRunnerMessage("The registered challenge digest changed.")
        if loaded.challenge.runtime_policy != job.runtime_policy:
            raise InvalidRunnerMessage("The registered runtime policy changed.")
        expected_definitions = {
            (test.id, test.test_definition_id, test.required_for_civilian_win)
            for test in loaded.challenge.tests
        }
        job_definitions = {
            (test.test_id, test.test_definition_id, test.required_for_civilian_win)
            for test in job.tests
        }
        if expected_definitions != job_definitions:
            raise InvalidRunnerMessage("The runner job does not match the authored challenge tests.")
        expected_tests = {test.test_id for test in job.tests}
        actual_tests = {test.test_id for test in result.tests}
        if result.status is RunnerStatus.COMPLETED and actual_tests != expected_tests:
            raise InvalidRunnerMessage("Completed result does not contain the exact registered test set.")

        lock = self._locks.setdefault(job.room_code, asyncio.Lock())
        async with lock:
            for _ in range(8):
                stored = await self._rooms.load_room(job.room_code)
                now = datetime.now(timezone.utc)
                if stored is None:
                    return True
                state = stored.state
                match = state.match
                current = match.current_round if match else None
                # A retry from an old round/match cannot affect current state.
                if (
                    match is None
                    or match.match_id != job.match_id
                ):
                    return True
                round_state = current if current and current.number == job.round_number else next(
                    (item for item in match.round_history if item.number == job.round_number),
                    None,
                )
                if (
                    round_state is None
                    or round_state.deadline.deadline_id != job.deadline_id
                    or round_state.challenge_id != job.challenge_id
                    or round_state.challenge_version != job.challenge_version
                    or round_state.challenge_content_digest != job.challenge_content_digest
                ):
                    return True
                if any(
                    progress.run_id == result.run_id
                    and progress.status is OfficialRunStatus.ERROR
                    for progress in round_state.official_run_progress
                ):
                    # A timed-out run cannot return later and alter a match.
                    return True
                if (
                    state.phase in {GamePhase.MEETING_DISCUSSION, GamePhase.PLAYER_VOTE}
                    and current is round_state
                    and round_state.current_source_revision_id == job.source_revision_id
                ):
                    # Meetings pause the coding deadline and editor. Keep the
                    # signed result pending until the ballot resumes the round.
                    return False
                if (
                    round_state.current_source_revision_id != job.source_revision_id
                    or state.phase is not GamePhase.CODING_ROUND
                    or current is not round_state
                ):
                    stale = record_official_run_status(
                        state,
                        round_number=job.round_number,
                        run_id=result.run_id,
                        source_revision_id=result.source_revision_id,
                        status=OfficialRunStatus.STALE,
                        now=now,
                        requested_by_player_id=job.requested_by_player_id,
                        requested_at=job.requested_at,
                    )
                    if isinstance(stale, TransitionAccepted) and stale.state != state:
                        if await self._commit_transition(stored, job.room_code, stale, None):
                            return True
                        continue
                    return True
                if result.status is RunnerStatus.RUNNING:
                    running = record_official_run_status(
                        state,
                        round_number=job.round_number,
                        run_id=result.run_id,
                        source_revision_id=result.source_revision_id,
                        status=OfficialRunStatus.RUNNING,
                        now=now,
                        requested_by_player_id=job.requested_by_player_id,
                        requested_at=job.requested_at,
                    )
                    if isinstance(running, TransitionAccepted):
                        if running.state == state:
                            return True
                        if await self._commit_transition(stored, job.room_code, running, None):
                            return True
                        continue
                    return True
                if result.status is not RunnerStatus.COMPLETED:
                    # Persist an explicit safe error status so clients can stop
                    # waiting and snapshots survive reconnects.
                    failed = record_official_run_status(
                        state,
                        round_number=job.round_number,
                        run_id=result.run_id,
                        source_revision_id=result.source_revision_id,
                        status=OfficialRunStatus.ERROR,
                        now=now,
                        requested_by_player_id=job.requested_by_player_id,
                        requested_at=job.requested_at,
                    )
                    if isinstance(failed, TransitionAccepted):
                        if failed.state == state:
                            await self._runner.release_deduplication(job)
                            return True
                        if await self._commit_transition(stored, job.room_code, failed, None):
                            await self._runner.release_deduplication(job)
                            return True
                        continue
                    return True

                if current.official_test_result is not None:
                    prior = current.official_test_result
                    if prior.run_id == result.run_id:
                        if (
                            prior.source_revision_id == result.source_revision_id
                            and prior.completed_at == result.completed_at
                            and set(prior.passed_test_ids) == {
                                item.test_id for item in result.tests if item.passed
                            }
                            and set(prior.failed_test_ids) == {
                                item.test_id for item in result.tests if not item.passed
                            }
                        ):
                            return True
                        raise InvalidRunnerMessage("A run ID was replayed with different verdicts.")

                required_ids = {
                    test.test_id for test in job.tests if test.required_for_civilian_win
                }
                passed_ids = tuple(test.test_id for test in result.tests if test.passed)
                failed_ids = tuple(test.test_id for test in result.tests if not test.passed)
                official = OfficialTestResult(
                    run_id=result.run_id,
                    source_revision_id=result.source_revision_id,
                    completed_at=result.completed_at,
                    passed_test_ids=passed_ids,
                    failed_test_ids=failed_ids,
                    all_required_tests_passed=required_ids.issubset(set(passed_ids)),
                )
                has_progress = any(
                    item.run_id == result.run_id
                    for item in current.official_run_progress
                )
                queued = (
                    TransitionAccepted(state=state)
                    if has_progress
                    else record_official_run_status(
                        state,
                        round_number=job.round_number,
                        run_id=result.run_id,
                        source_revision_id=result.source_revision_id,
                        status=OfficialRunStatus.QUEUED,
                        now=now,
                        requested_by_player_id=job.requested_by_player_id,
                        requested_at=job.requested_at,
                    )
                )
                if not isinstance(queued, TransitionAccepted):
                    return True
                outcome = record_official_test_result(queued.state, official, now)
                if not isinstance(outcome, TransitionAccepted):
                    # A result that became late while being processed cannot
                    # change the match or publish a misleading pass state.
                    return True
                if queued.events:
                    outcome = TransitionAccepted(
                        state=outcome.state,
                        events=(*queued.events, *outcome.events),
                    )

                # The saved author chain and trusted behavioral checks must
                # both agree; a civilian regression is never sabotage credit.
                document = None
                if loaded.challenge.sabotage_objectives:
                    document = await self._rooms.load_editor_document(editor_document_id(state))
                for objective in loaded.challenge.sabotage_objectives:
                    if not attributable_regression(state, loaded.challenge, objective, document, result):
                        continue
                    verified = record_verified_sabotage_objective(
                        outcome.state, objective.id, result.source_revision_id, now,
                    )
                    if isinstance(verified, TransitionAccepted):
                        outcome = TransitionAccepted(
                            state=verified.state, events=(*outcome.events, *verified.events),
                        )
                payload = player_safe_result_payload(loaded.challenge, result)
                if await self._commit_transition(stored, job.room_code, outcome, payload):
                    return True
            return False

    async def _commit_transition(self, stored, room_code: str, outcome, payload: dict[str, object] | None) -> bool:
        sequence = stored.sequence + 1
        projected = tuple(project_event(event, sequence) for event in outcome.events)
        if not await self._rooms.compare_and_swap(
            stored, outcome.state, advance_sequence=bool(outcome.events),
        ):
            return False
        if payload is not None:
            await self._connections.broadcast(
                room_code,
                ServerEvent(sequence=sequence, name="OfficialTestResult", payload=payload),
            )
        for recipient, event in projected:
            if recipient is None:
                if self._metrics is not None:
                    self._metrics.observe_public_event(event.name, event.payload)
                await self._connections.broadcast(room_code, event)
            else:
                await self._connections.send_private(room_code, recipient, event)
        return True


def _match_job(result: RunnerResult, job: RunnerJob) -> None:
    pairs = (
        (result.protocol_version, job.protocol_version),
        (result.run_id, job.run_id),
        (result.room_code, job.room_code),
        (result.match_id, job.match_id),
        (result.round_number, job.round_number),
        (result.deadline_id, job.deadline_id),
        (result.challenge_id, job.challenge_id),
        (result.challenge_version, job.challenge_version),
        (result.challenge_content_digest, job.challenge_content_digest),
        (result.source_revision_id, job.source_revision_id),
    )
    if any(actual != expected for actual, expected in pairs):
        raise InvalidRunnerMessage("Runner result identity does not match its job.")
    if result.started_at < job.requested_at:
        raise InvalidRunnerMessage("Runner execution predates its request.")
