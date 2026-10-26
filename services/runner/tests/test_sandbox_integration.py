"""Run inside the Linux runner container to exercise actual namespaces/limits."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import tempfile
import unittest

from challenges.registry import COUNTER, COUNTER_1_1, STACK, WALLET, ChallengeSpec, resolve_job
from contracts import TestFailureKind, TestCase
from executor import JAIL_BINARY, RunnerExecutor
from test_contract_and_parser import job


JAIL_AVAILABLE = os.name == "posix" and Path(JAIL_BINARY).is_file()


@unittest.skipUnless(JAIL_AVAILABLE, "requires the Linux runner image with nsjail")
class SandboxIntegrationTests(unittest.TestCase):
    def run_cases(self, source: str, *, all_tests: bool = False):
        async def execute():
            with tempfile.TemporaryDirectory(dir="/runs") as directory:
                executor = RunnerExecutor(Path(directory))
                await executor.preflight()
                spec = ChallengeSpec(
                    challenge_id=COUNTER.challenge_id, version=COUNTER.version,
                    content_digest=COUNTER.content_digest,
                    runtime_policy=COUNTER.runtime_policy,
                    tests=COUNTER.tests if all_tests else COUNTER.tests[:1],
                )
                return await executor.execute(job(source=source), spec)
        return asyncio.run(execute())

    def test_correct_code_passes(self):
        source = """class Counter:
    def __init__(self):
        self.count = 0
        self.history = []
    def increment(self):
        self.count += 1
        self.history.append('inc')
    def decrement(self):
        self.count -= 1
        self.history.append('dec')
    def reset(self):
        self.count = 0
        self.history.append('reset')
    def value(self):
        return self.count
"""
        self.assertTrue(all(result.passed for result in self.run_cases(source, all_tests=True)))

    def test_all_authored_references_pass_in_the_real_jail(self):
        async def execute(spec):
            source = (Path(__file__).parent / "fixtures" / (spec.challenge_id.replace(".", "_") + ".py")).read_text()
            pinned = job(source=source).model_copy(update={
                "challenge_id": spec.challenge_id, "challenge_version": spec.version,
                "challenge_content_digest": spec.content_digest,
                "tests": tuple(TestCase(test_id=t.test_id, test_definition_id=t.definition_id,
                                        required_for_civilian_win=t.required_for_civilian_win) for t in spec.tests),
            })
            self.assertIs(resolve_job(pinned), spec)
            with tempfile.TemporaryDirectory(dir="/runs") as directory:
                return await RunnerExecutor(Path(directory)).execute(pinned, spec)
        for spec in (COUNTER_1_1, STACK, WALLET):
            with self.subTest(challenge=spec.challenge_id):
                results = asyncio.run(execute(spec))
                self.assertTrue(all(result.passed for result in results), results)

    def test_runaway_loop_is_bounded(self):
        result = self.run_cases("while True: pass\nclass Counter: pass")[0]
        self.assertFalse(result.passed)
        self.assertEqual(result.failure_kind, TestFailureKind.TIMEOUT)

    def test_malformed_python_and_excessive_output_fail(self):
        for source in ("def broken(: pass", "import sys\nsys.__stdout__.write('x' * 100000)\nclass Counter: pass"):
            with self.subTest(source=source[:30]):
                result = self.run_cases(source)[0]
                self.assertFalse(result.passed)
                self.assertEqual(result.failure_kind, TestFailureKind.EXCEPTION)

    def test_filesystem_and_network_access_attempts_fail(self):
        for action in (
            "open('/etc/passwd').read()",
            "open('/opt/runner/worker.py').read()",
            "__import__('socket').socket()",
            "__import__('challenges.registry')",
        ):
            source = f"class Counter:\n    def __init__(self):\n        {action}\n"
            with self.subTest(action=action):
                result = self.run_cases(source)[0]
                self.assertFalse(result.passed)

    def test_memory_and_process_creation_limits(self):
        for action in ("bytearray(600_000_000)", "__import__('os').fork()"):
            source = f"class Counter:\n    def __init__(self):\n        {action}\n"
            with self.subTest(action=action):
                self.assertFalse(self.run_cases(source)[0].passed)

    def test_jail_does_not_inherit_runner_signing_key(self):
        source = """import os
class Counter:
    def __init__(self):
        assert 'CODEMAFIA_RUNNER_RESULT_HMAC_KEY' not in os.environ
        self.count = 0
        self.history = []
    def increment(self):
        self.count += 1
        self.history.append('inc')
"""
        self.assertTrue(self.run_cases(source)[0].passed)

    def test_every_run_removes_its_source_directory(self):
        with tempfile.TemporaryDirectory(dir="/runs") as directory:
            runs_dir = Path(directory)
            executor = RunnerExecutor(runs_dir)
            spec = ChallengeSpec(
                challenge_id=COUNTER.challenge_id, version=COUNTER.version,
                content_digest=COUNTER.content_digest,
                runtime_policy=COUNTER.runtime_policy, tests=COUNTER.tests[:1],
            )
            source = """class Counter:
    def __init__(self):
        self.count = 0
        self.history = []
    def increment(self):
        self.count += 1
        self.history.append('inc')
"""
            asyncio.run(executor.execute(job(source=source), spec))
            self.assertEqual(list(runs_dir.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
