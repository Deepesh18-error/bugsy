"""Drive one fresh nsjail process per trusted test of a submitted source."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import json
import os
from pathlib import Path
import secrets
import signal
import tempfile
from time import monotonic

from challenges.registry import ChallengeSpec
from contracts import RunnerJob, TestFailureKind, TestResult
from result_parser import SandboxProtocolError, parse_ready, parse_reply, read_document


JAIL_BINARY = "/usr/local/bin/nsjail"
JAIL_CONFIG = "/opt/runner/sandbox/nsjail.cfg"
SANDBOX_SCRIPT = "/opt/runner/sandbox/run_submission.py"
PYTHON_BINARY = "/usr/local/bin/python3"
SANDBOX_WALL_SECONDS = 5.0
STARTUP_SECONDS = 2.5


class RunnerInfrastructureError(RuntimeError):
    """The jail could not be started or controlled safely."""


class SandboxOperationError(RuntimeError):
    """The submission failed an operation or broke its bounded protocol."""


class SandboxTestTimeout(SandboxOperationError):
    """A submission exceeded the per-test wall-time budget."""


class CounterSession:
    """Typed parent-side facade over the jailed source's small operation API."""

    def __init__(self, source_dir: Path) -> None:
        self._source_dir = source_dir
        self._process: asyncio.subprocess.Process | None = None
        self._deadline = 0.0

    async def __aenter__(self) -> CounterSession:
        if os.name != "posix":
            raise RunnerInfrastructureError("nsjail execution requires a Linux host")
        args = [
            JAIL_BINARY, "--config", JAIL_CONFIG,
            "--bindmount_ro", f"{self._source_dir}:/work",
            "--", PYTHON_BINARY, "-I", "-B", SANDBOX_SCRIPT, "/work/submission.py",
        ]
        try:
            self._process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                limit=4_097,
                start_new_session=True,
                env={"PATH": "/usr/local/bin:/usr/bin:/bin"},
            )
            self._deadline = monotonic() + SANDBOX_WALL_SECONDS
            assert self._process.stdout is not None
            ready = await asyncio.wait_for(read_document(self._process.stdout), timeout=STARTUP_SECONDS)
            parse_ready(ready)
            return self
        except (OSError, TimeoutError, SandboxProtocolError) as exc:
            await self._stop()
            raise RunnerInfrastructureError("nsjail failed its startup handshake") from exc
        except BaseException:
            await self._stop()
            raise

    async def __aexit__(self, *_: object) -> None:
        await self._stop()

    async def _stop(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        if process.returncode is None:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        with suppress(Exception):
            await asyncio.wait_for(process.wait(), timeout=1.0)

    async def _request(self, operation: str, name: str | None = None) -> object:
        process = self._process
        if process is None or process.stdin is None or process.stdout is None:
            raise RunnerInfrastructureError("jail process is unavailable")
        nonce = secrets.token_hex(16)
        request: dict[str, str] = {"op": operation, "nonce": nonce}
        if name is not None:
            request["name"] = name
        payload = json.dumps(request, separators=(",", ":")).encode("utf-8") + b"\n"
        remaining = self._deadline - monotonic()
        if remaining <= 0:
            raise SandboxTestTimeout("test deadline exceeded")
        try:
            process.stdin.write(payload)
            await asyncio.wait_for(process.stdin.drain(), timeout=remaining)
            response = await asyncio.wait_for(read_document(process.stdout),
                                              timeout=max(0.001, self._deadline - monotonic()))
            parsed = parse_reply(response, nonce)
        except TimeoutError as exc:
            raise SandboxTestTimeout("test deadline exceeded") from exc
        except SandboxProtocolError as exc:
            if monotonic() >= self._deadline - 1.5:
                raise SandboxTestTimeout("jail exceeded its time budget") from exc
            raise SandboxOperationError("submission failed its operation protocol") from exc
        except (BrokenPipeError, ConnectionResetError, ValueError) as exc:
            raise SandboxOperationError("submission failed its operation protocol") from exc
        if not parsed.ok:
            raise SandboxOperationError("submission operation raised an exception")
        return parsed.value

    async def construct(self) -> None:
        await self._request("construct")

    async def call(self, method: str) -> object:
        return await self._request("call", method)

    async def read(self, attribute: str) -> object:
        return await self._request("read", attribute)


class RunnerExecutor:
    def __init__(self, runs_dir: Path) -> None:
        if not runs_dir.is_dir():
            raise ValueError("runner scratch directory does not exist")
        self._runs_dir = runs_dir.resolve(strict=True)

    async def preflight(self) -> None:
        """Fail startup if this host cannot create the required isolated jail."""

        with tempfile.TemporaryDirectory(prefix="preflight-", dir=self._runs_dir) as directory:
            source_dir = Path(directory)
            source_path = source_dir / "submission.py"
            fd = os.open(source_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write("class Counter:\n    def __init__(self):\n        self.count = 0\n")
            async with CounterSession(source_dir) as session:
                await session.construct()
                if await session.read("count") != 0:
                    raise RunnerInfrastructureError("nsjail preflight returned an invalid value")

    async def execute(self, job: RunnerJob, challenge: ChallengeSpec) -> tuple[TestResult, ...]:
        """Run the trusted checks; all player code stays in disposable jails."""

        results: list[TestResult] = []
        with tempfile.TemporaryDirectory(prefix="run-", dir=self._runs_dir) as directory:
            source_dir = Path(directory)
            source_path = source_dir / "submission.py"
            fd = os.open(source_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(job.source)
            for test in challenge.tests:
                try:
                    async with CounterSession(source_dir) as session:
                        await test.run(session)
                except SandboxTestTimeout:
                    results.append(TestResult(test_id=test.test_id, passed=False,
                                              failure_kind=TestFailureKind.TIMEOUT))
                except AssertionError:
                    results.append(TestResult(test_id=test.test_id, passed=False,
                                              failure_kind=TestFailureKind.ASSERTION))
                except SandboxOperationError:
                    results.append(TestResult(test_id=test.test_id, passed=False,
                                              failure_kind=TestFailureKind.EXCEPTION))
                # RunnerInfrastructureError is deliberately not converted into
                # a test failure; unavailable isolation must fail the whole run.
                else:
                    results.append(TestResult(test_id=test.test_id, passed=True))
        return tuple(results)
