"""Official jobs use saved source; only signed, current results enter game state."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import importlib.util
from pathlib import Path
import sys
import unittest

from pydantic import ValidationError

from app.api.schemas import build_room_response
from app.game.commands import RequestOfficialTestRun
from app.game.models import GamePhase, MatchEndReason, SabotageObjectiveProgress, TestPassEvidence
from app.rooms.repository import StoredRoom
from app.rooms.serialization import serialize_room
from app.runner.contracts import (
    MAX_JOB_BYTES, RunnerResult, RunnerStatus, RunnerTestResult,
    RunnerEnqueueReceipt, RunnerQueueState, TestFailureKind,
    encode_model, sign_result, verify_result_signature,
)
from app.runner.result_processor import InvalidRunnerMessage, RunnerResultProcessor
from app.runner.service import RunnerQueueFull, RunnerService, RunnerUnavailable
from runner_support import FakeConnections, FakeRooms, FakeRunner, KEY, LOADED, NOW, coding_room, run_immediate


def signed_result(job, *, fail_test_id: str | None = None) -> RunnerResult:
    tests = tuple(RunnerTestResult(
        test_id=item.test_id, passed=item.test_id != fail_test_id,
        failure_kind=TestFailureKind.ASSERTION if item.test_id == fail_test_id else None,
    ) for item in job.tests)
    provisional = RunnerResult(
        run_id=job.run_id, room_code=job.room_code, match_id=job.match_id,
        round_number=job.round_number, deadline_id=job.deadline_id,
        challenge_id=job.challenge_id, challenge_version=job.challenge_version,
        challenge_content_digest=job.challenge_content_digest,
        source_revision_id=job.source_revision_id, status=RunnerStatus.COMPLETED,
        started_at=job.requested_at, completed_at=job.requested_at,
        tests=tests, signature="0" * 64,
    )
    signature = sign_result(provisional.model_dump(mode="json", exclude={"signature"}), KEY)
    return provisional.model_copy(update={"signature": signature})


class RunnerFlowTests(unittest.TestCase):
    def setUp(self):
        self.source = "class Counter:\n    def __init__(self): self.count = 42\n"
        self.rooms = FakeRooms(coding_room(), self.source)
        self.runner = FakeRunner()
        self.connections = FakeConnections()
        self.service = RunnerService(self.rooms, self.runner)

    async def queue(self):
        command = RequestOfficialTestRun(
            request_id="request-1", player_id="player-1", source_revision_id="revision-1",
        )
        return await self.service.enqueue_for_request(self.rooms.stored, command, NOW)

    def test_job_contains_saved_source_and_all_pinned_tests(self):
        receipt = run_immediate(self.queue())
        job = self.runner.job
        self.assertEqual(receipt.run_id, job.run_id)
        self.assertEqual(job.source, self.source)
        self.assertEqual(job.challenge_content_digest, LOADED.content_digest)
        self.assertEqual({item.test_id for item in job.tests},
                         {item.id for item in LOADED.challenge.tests})

    def test_unsaved_revision_cannot_be_submitted(self):
        self.rooms.document = self.rooms.document.__class__(
            revision_id="revision-older", source=self.source, y_state="eA==",
        )
        with self.assertRaises(RunnerUnavailable):
            run_immediate(self.queue())
        self.assertIsNone(self.runner.job)

    def test_full_queue_rejects_request_without_claiming_an_official_run(self):
        async def full(_job):
            return RunnerEnqueueReceipt(state=RunnerQueueState.FULL)
        self.runner.enqueue_job = full
        with self.assertRaises(RunnerQueueFull):
            run_immediate(self.queue())

    def test_result_is_accepted_only_for_current_revision_and_hidden_ids_stay_private(self):
        run_immediate(self.queue())
        hidden = next(item.id for item in LOADED.challenge.tests if item.visibility == "hidden")
        result = signed_result(self.runner.job, fail_test_id=hidden)
        processor = RunnerResultProcessor(self.rooms, self.runner, self.connections, signing_key=KEY)
        self.assertTrue(run_immediate(processor.process(result)))
        self.assertEqual(self.rooms.commits, 1)
        self.assertEqual(self.rooms.stored.state.match.current_round.official_test_result.run_id,
                         result.run_id)
        event = next(event for _, event in self.connections.public if event.name == "OfficialTestResult")
        self.assertNotIn(hidden, str(event.payload))
        snapshot = build_room_response(self.rooms.stored.state, "player-1").room
        self.assertNotIn(hidden, snapshot.model_dump_json())
        self.assertEqual(snapshot.official_result.source_revision_id, "revision-1")
        self.assertFalse(snapshot.official_result.all_required_tests_passed)
        self.assertTrue(run_immediate(processor.process(result)))
        self.assertEqual(self.rooms.commits, 1)

    def test_stale_and_forged_results_do_not_change_room(self):
        run_immediate(self.queue())
        result = signed_result(self.runner.job)
        processor = RunnerResultProcessor(self.rooms, self.runner, self.connections, signing_key=KEY)
        with self.assertRaises(InvalidRunnerMessage):
            run_immediate(processor.process(result.model_copy(update={"signature": "0" * 64})))
        self.rooms.change_revision("revision-2")
        self.assertTrue(run_immediate(processor.process(result)))
        self.assertEqual(self.rooms.commits, 1)
        self.assertIsNone(self.rooms.stored.state.match.current_round.official_test_result)
        self.assertEqual(self.rooms.stored.state.match.current_round.official_run_progress[-1].status.value, "stale")
        self.assertFalse(any(event.name == "OfficialTestResult" for _, event in self.connections.public))

    def test_infrastructure_error_is_visible_and_allows_retry(self):
        run_immediate(self.queue())
        job = self.runner.job
        result = RunnerResult(
            run_id=job.run_id, room_code=job.room_code, match_id=job.match_id,
            round_number=job.round_number, deadline_id=job.deadline_id,
            challenge_id=job.challenge_id, challenge_version=job.challenge_version,
            challenge_content_digest=job.challenge_content_digest,
            source_revision_id=job.source_revision_id, status=RunnerStatus.RUNNER_ERROR,
            started_at=job.requested_at, completed_at=job.requested_at,
            tests=(), signature="0" * 64,
        )
        result = result.model_copy(update={"signature": sign_result(
            result.model_dump(mode="json", exclude={"signature"}), KEY,
        )})
        processor = RunnerResultProcessor(self.rooms, self.runner, self.connections, signing_key=KEY)
        self.assertTrue(run_immediate(processor.process(result)))
        snapshot = build_room_response(self.rooms.stored.state, "player-1").room
        self.assertEqual(snapshot.official_runs[-1].status.value, "error")
        self.assertIsNone(snapshot.official_result)
        self.assertIn(job.run_id, self.runner.released)

    def test_private_objective_description_is_only_in_impostor_snapshot(self):
        state = self.rooms.stored.state
        objective_id = LOADED.challenge.sabotage_objectives[0].id
        current = replace(state.match.current_round, sabotage_objectives=(
            SabotageObjectiveProgress(objective_id=objective_id),
        ))
        state = replace(state, match=replace(state.match, current_round=current))
        civilian = build_room_response(state, "player-1").room
        impostor = build_room_response(state, "player-4").room
        self.assertEqual(civilian.own_objectives, ())
        self.assertEqual(impostor.own_objectives[0].objective_id, objective_id)
        self.assertIn("decrement", impostor.own_objectives[0].private_description)
        self.assertNotIn("private_description", civilian.model_dump_json())

    def test_signed_regression_verifies_private_objective(self):
        state = self.rooms.stored.state
        objective = LOADED.challenge.sabotage_objectives[0]
        earlier_pass = TestPassEvidence(
            test_id=objective.verification.test_id,
            source_revision_id="revision-before-sabotage",
            run_id="prior-pass", completed_at=NOW - timedelta(seconds=1),
        )
        current = replace(state.match.current_round,
            test_pass_evidence=(earlier_pass,),
            sabotage_objectives=(SabotageObjectiveProgress(objective_id=objective.id),),
        )
        state = replace(state, match=replace(state.match, current_round=current))
        self.rooms.stored = StoredRoom(state, serialize_room(state), 0)
        run_immediate(self.queue())
        result = signed_result(self.runner.job, fail_test_id=objective.verification.test_id)
        processor = RunnerResultProcessor(self.rooms, self.runner, self.connections, signing_key=KEY)
        self.assertTrue(run_immediate(processor.process(result)))
        final = self.rooms.stored.state
        self.assertEqual(final.phase, GamePhase.GAME_OVER)
        self.assertEqual(final.match.result.reason, MatchEndReason.SABOTAGE_OBJECTIVES_COMPLETED)
        objective_events = [event for _, _, event in self.connections.private
                            if event.name == "SabotageObjectiveVerified"]
        self.assertEqual(len(objective_events), 1)
        self.assertFalse(any(event.name == "SabotageObjectiveVerified"
                             for _, event in self.connections.public))

    def test_wire_result_rejects_coerced_pass_values(self):
        with self.assertRaises(ValidationError):
            RunnerTestResult(test_id="test-a", passed="yes")

    def test_api_and_independent_runner_agree_on_wire_messages(self):
        run_immediate(self.queue())
        path = Path(__file__).resolve().parents[3] / "services" / "runner" / "contracts.py"
        spec = importlib.util.spec_from_file_location("independent_runner_contracts", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        runner_job = module.decode_job(encode_model(self.runner.job, maximum_bytes=MAX_JOB_BYTES))
        self.assertEqual(runner_job.source, self.source)
        tests = tuple(module.TestResult(test_id=item.test_id, passed=True)
                      for item in runner_job.tests)
        raw_result = module.make_signed_result(
            runner_job, status=module.RunnerStatus.COMPLETED,
            started_at=runner_job.requested_at, completed_at=runner_job.requested_at,
            tests=tests, signing_key=KEY,
        )
        result = RunnerResult.model_validate_json(raw_result)
        self.assertTrue(verify_result_signature(result, KEY))


if __name__ == "__main__":
    unittest.main()
