"""Run inside the Linux runner container to exercise actual namespaces/limits."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import tempfile
import unittest

from challenges.registry import COUNTER, ChallengeSpec
from contracts import TestFailureKind
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
        for action in ("open('/etc/passwd').read()", "__import__('socket').socket()"):
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


if __name__ == "__main__":
    unittest.main()
