"""Authenticate runner results and commit only current, complete verdicts."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.api.websocket_schemas import ServerEvent
from app.challenges.loader import ChallengeLoadError, load_challenge
from app.game.models import GamePhase, OfficialTestResult
from app.game.outcomes import TransitionAccepted
from app.game.transitions import record_official_test_result
from app.realtime.connection_manager import RoomConnectionManager
from app.realtime.snapshots import project_event
from app.rooms.repository import RoomRepository
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
    ) -> None:
        if len(signing_key.encode("utf-8")) < 32:
            raise ValueError("CODEMAFIA_RUNNER_RESULT_HMAC_KEY must contain at least 32 bytes.")
        self._rooms = rooms
        self._runner = runner
        self._connections = connections
        self._signing_key = signing_key
        self._locks = room_locks if room_locks is not None else {}

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
                # Stale results are expected after edits, deadline resolution,
                # rematches, or room expiry. They are discarded and ACKed.
                if (
                    state.phase is not GamePhase.CODING_ROUND
                    or match is None
                    or match.match_id != job.match_id
                    or current is None
                    or current.number != job.round_number
                    or current.deadline.deadline_id != job.deadline_id
                    or current.challenge_id != job.challenge_id
                    or current.challenge_version != job.challenge_version
                    or current.challenge_content_digest != job.challenge_content_digest
                    or current.current_source_revision_id != job.source_revision_id
                ):
                    return True
                if result.status is not RunnerStatus.COMPLETED:
                    # Infrastructure failures carry no test verdict. ACK them
                    # without advancing the game sequence; a later retry can
                    # request another run, and replay cannot create duplicate
                    # failure notifications.
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
                outcome = record_official_test_result(state, official, now)
                if not isinstance(outcome, TransitionAccepted):
                    # A result that became late while being processed cannot
                    # change the match or publish a misleading pass state.
                    return True
                payload = player_safe_result_payload(loaded.challenge, result)
                if await self._commit_transition(stored, job.room_code, outcome, payload):
                    return True
            return False

    async def _commit_transition(self, stored, room_code: str, outcome, payload: dict[str, object]) -> bool:
        sequence = stored.sequence + 1
        projected = tuple(project_event(event, sequence) for event in outcome.events)
        if not await self._rooms.compare_and_swap(
            stored, outcome.state, advance_sequence=not outcome.events,
        ):
            return False
        await self._connections.broadcast(
            room_code,
            ServerEvent(sequence=sequence, name="OfficialTestResult", payload=payload),
        )
        for recipient, event in projected:
            if recipient is None:
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
