"""Checks the runner's independent allowlist and untrusted-output parser."""

from __future__ import annotations

from datetime import datetime, timezone
import os
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from challenges.registry import COUNTER, resolve_job
from contracts import RunnerJob, TestCase, TestResult
from result_parser import SandboxProtocolError, parse_ready, parse_reply
from sandbox.run_submission import DiscardPlayerOutput
from worker import WorkerSettings


def job(*, tests=None, digest=None, source="class Counter: pass") -> RunnerJob:
    return RunnerJob(
        run_id="a" * 32, room_code="TEST42", match_id="match-1", round_number=1,
        deadline_id="deadline-1", challenge_id=COUNTER.challenge_id,
        challenge_version=COUNTER.version, challenge_content_digest=digest or COUNTER.content_digest,
        runtime_policy="python-standard-v1", source_revision_id="revision-1",
        source=source, requested_by_player_id="player-1", request_id="request-1",
        requested_at=datetime.now(timezone.utc), dedupe_key="b" * 64,
        tests=tests or tuple(TestCase(
            test_id=item.test_id, test_definition_id=item.definition_id,
            required_for_civilian_win=item.required_for_civilian_win,
        ) for item in COUNTER.tests),
    )


class RunnerBoundaryTests(unittest.TestCase):
    def test_exact_content_and_test_list_are_required(self):
        self.assertIs(resolve_job(job()), COUNTER)
        with self.assertRaises(ValueError):
            resolve_job(job(digest="sha256:" + "0" * 64))
        with self.assertRaises(ValueError):
            resolve_job(job(tests=job().tests[:-1]))

    def test_contract_rejects_oversized_source_and_coerced_verdict(self):
        with self.assertRaises(ValidationError):
            job(source="x" * 65_537)
        with self.assertRaises(ValidationError):
            TestResult(test_id="test-a", passed="true")

    def test_jail_reply_requires_exact_nonce_and_shape(self):
        parse_ready({"type": "ready", "protocol_version": 1})
        self.assertEqual(parse_reply({"nonce": "n", "ok": True, "value": 1}, "n").value, 1)
        for reply in (
            {"nonce": "wrong", "ok": True, "value": 1},
            {"nonce": "n", "ok": True, "value": 1, "passed": True},
            {"nonce": "n", "ok": "true", "value": 1},
        ):
            with self.subTest(reply=reply), self.assertRaises(SandboxProtocolError):
                parse_reply(reply, "n")

    def test_print_budget_is_bounded(self):
        sink = DiscardPlayerOutput()
        self.assertEqual(sink.write("x" * 4_096), 4_096)
        with self.assertRaises(RuntimeError):
            sink.write("x")

    def test_parallel_job_limit_is_enforced_at_configuration(self):
        base = {"REDIS_URL": "redis://redis:6379/0",
                "CODEMAFIA_RUNNER_RESULT_HMAC_KEY": "x" * 32}
        with patch.dict(os.environ, {**base, "CODEMAFIA_RUNNER_MAX_CONCURRENCY": "4"}):
            self.assertEqual(WorkerSettings().concurrency, 4)
        with patch.dict(os.environ, {**base, "CODEMAFIA_RUNNER_MAX_CONCURRENCY": "5"}):
            with self.assertRaises(ValueError):
                WorkerSettings()


if __name__ == "__main__":
    unittest.main()
