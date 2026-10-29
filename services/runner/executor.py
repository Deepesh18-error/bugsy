"""Drive one fresh nsjail process per trusted test of a submitted source."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import json
import os
import re
from pathlib import Path
import secrets
import signal
import tempfile
from time import monotonic

from challenges.registry import ChallengeSpec
from contracts import RunnerJob, TestFailureKind, TestResult
from result_parser import SandboxClosedError, SandboxProtocolError, parse_ready, parse_reply, read_document


JAIL_BINARY = "/usr/local/bin/nsjail"
JAIL_CONFIG = "/opt/runner/sandbox/nsjail.cfg"
SANDBOX_SCRIPT = "/opt/runner/sandbox/run_submission.py"
PYTHON_BINARY = "/usr/local/bin/python3"
SANDBOX_WALL_SECONDS = 5.0
SANDBOX_CPU_SECONDS = 2.0  # Matches rlimit_cpu in sandbox/nsjail.cfg.
STARTUP_SECONDS = 2.5
CPP_COMPILE_CONFIG = "/opt/runner/sandbox/nsjail_cpp_compile.cfg"
CPP_HARNESS = "/opt/runner/sandbox/cpp_score_harness.cpp"
CPP_BINARY = "/work/program"


class RunnerInfrastructureError(RuntimeError):
    """The jail could not be started or controlled safely."""


class SandboxOperationError(RuntimeError):
    """The submission failed an operation or broke its bounded protocol."""


class SandboxTestTimeout(SandboxOperationError):
    """A submission exceeded the per-test wall-time budget."""


class CounterSession:
    """Typed parent-side facade over the jailed source's small operation API."""

    def __init__(self, source_dir: Path, *, capture_startup_diagnostics: bool = False) -> None:
        self._source_dir = source_dir
        self._capture_startup_diagnostics = capture_startup_diagnostics
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
                stderr=(asyncio.subprocess.PIPE if self._capture_startup_diagnostics
                        else asyncio.subprocess.DEVNULL),
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
            diagnostic = (await self._stop()).decode("utf-8", errors="replace").strip()
            message = "nsjail failed its startup handshake"
            if diagnostic:
                message += f": {diagnostic}"
            raise RunnerInfrastructureError(message) from exc
        except BaseException:
            await self._stop()
            raise

    async def __aexit__(self, *_: object) -> None:
        await self._stop()

    async def _stop(self) -> bytes:
        process = self._process
        self._process = None
        if process is None:
            return b""
        if process.returncode is None:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        try:
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=1.0)
            return (stderr or b"")[:4096]
        except Exception:
            with suppress(Exception):
                await asyncio.wait_for(process.wait(), timeout=0.5)
            return b""

    async def _request(self, operation: str, name: str | None = None, arguments: tuple = ()) -> object:
        process = self._process
        if process is None or process.stdin is None or process.stdout is None:
            raise RunnerInfrastructureError("jail process is unavailable")
        nonce = secrets.token_hex(16)
        request: dict[str, object] = {"op": operation, "nonce": nonce}
        if name is not None:
            request["name"] = name
        if arguments:
            request["args"] = arguments
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
        except SandboxClosedError as exc:
            # nsjail's CPU limit can terminate a loop before the wall deadline.
            cpu_cutoff = self._deadline - SANDBOX_WALL_SECONDS + SANDBOX_CPU_SECONDS - 0.5
            if monotonic() >= cpu_cutoff:
                raise SandboxTestTimeout("jail exceeded its CPU time budget") from exc
            raise SandboxOperationError("submission ended before replying") from exc
        except SandboxProtocolError as exc:
            if monotonic() >= self._deadline - 1.5:
                raise SandboxTestTimeout("jail exceeded its time budget") from exc
            raise SandboxOperationError("submission failed its operation protocol") from exc
        except (BrokenPipeError, ConnectionResetError, ValueError) as exc:
            raise SandboxOperationError("submission failed its operation protocol") from exc
        if not parsed.ok:
            raise SandboxOperationError("submission operation raised an exception")
        return parsed.value

    async def construct(self, name: str = "Counter") -> None:
        await self._request("construct", name)

    async def call(self, method: str, *arguments: object) -> object:
        return await self._request("call", method, arguments)

    async def read(self, attribute: str) -> object:
        return await self._request("read", attribute)


async def _compile_cpp(source_dir: Path) -> bool:
    """Compile untrusted C++ only inside its own bounded, networkless jail."""
    args = [JAIL_BINARY, "--config", CPP_COMPILE_CONFIG,
            "--bindmount", f"{source_dir}:/work", "--", "/usr/bin/g++",
            "-std=c++20", "-O0", "-o", CPP_BINARY,
            "/work/submission.cpp", CPP_HARNESS]
    try:
        process = await asyncio.create_subprocess_exec(
            *args, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True, env={"PATH": "/usr/bin:/bin"},
        )
    except OSError as exc:
        raise RunnerInfrastructureError("C++ compiler jail could not start") from exc
    try:
        return await asyncio.wait_for(process.wait(), timeout=14.0) == 0 and (source_dir / "program").is_file()
    except TimeoutError:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        await process.wait()
        raise SandboxTestTimeout("C++ compilation exceeded its time limit")


class CppScoreSession:
    def __init__(self, source_dir: Path) -> None:
        self._source_dir = source_dir
        self._process: asyncio.subprocess.Process | None = None
        self._deadline = 0.0

    async def __aenter__(self) -> CppScoreSession:
        try:
            self._process = await asyncio.create_subprocess_exec(
                JAIL_BINARY, "--config", JAIL_CONFIG,
                "--bindmount_ro", f"{self._source_dir}:/work", "--", CPP_BINARY,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, limit=4097,
                start_new_session=True, env={"PATH": "/usr/bin:/bin"},
            )
        except OSError as exc:
            raise RunnerInfrastructureError("C++ runtime jail could not start") from exc
        self._deadline = monotonic() + SANDBOX_WALL_SECONDS
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._process is not None:
            if self._process.returncode is None:
                with suppress(ProcessLookupError):
                    os.killpg(self._process.pid, signal.SIGKILL)
            await self._process.wait()
            self._process = None

    async def score(self, operation: str, current: int, points: int) -> int:
        process = self._process
        if process is None or process.stdin is None or process.stdout is None:
            raise RunnerInfrastructureError("C++ runtime jail is unavailable")
        if operation not in {"add", "subtract", "reset"}:
            raise ValueError("unknown C++ test operation")
        nonce = secrets.token_hex(16)
        try:
            process.stdin.write(f"{nonce} {operation} {current} {points}\n".encode("ascii"))
            remaining = max(0.001, self._deadline - monotonic())
            await asyncio.wait_for(process.stdin.drain(), timeout=remaining)
            line = await asyncio.wait_for(process.stdout.readline(), timeout=max(0.001, self._deadline - monotonic()))
        except TimeoutError as exc:
            raise SandboxTestTimeout("C++ test deadline exceeded") from exc
        except (BrokenPipeError, ConnectionResetError, ValueError) as exc:
            raise SandboxOperationError("C++ program ended before replying") from exc
        if not line or len(line) > 128:
            raise SandboxOperationError("C++ program returned an invalid response")
        match = re.fullmatch(rb"([0-9a-f]{32}) (-?[0-9]+)\n", line)
        if match is None or match.group(1).decode("ascii") != nonce:
            raise SandboxOperationError("C++ program returned an invalid response")
        return int(match.group(2))


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
            async with CounterSession(source_dir, capture_startup_diagnostics=True) as session:
                await session.construct()
                if await session.read("count") != 0:
                    raise RunnerInfrastructureError("nsjail preflight returned an invalid value")

    async def execute(self, job: RunnerJob, challenge: ChallengeSpec) -> tuple[TestResult, ...]:
        """Run the trusted checks; all player code stays in disposable jails."""

        results: list[TestResult] = []
        with tempfile.TemporaryDirectory(prefix="run-", dir=self._runs_dir) as directory:
            source_dir = Path(directory)
            is_cpp = challenge.runtime_policy == "cpp20-standard-v1"
            source_path = source_dir / ("submission.cpp" if is_cpp else "submission.py")
            fd = os.open(source_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(job.source)
            compile_failure: TestFailureKind | None = None
            if is_cpp:
                try:
                    if not await _compile_cpp(source_dir):
                        compile_failure = TestFailureKind.COMPILE_ERROR
                except SandboxTestTimeout:
                    compile_failure = TestFailureKind.TIMEOUT
            for test in challenge.tests:
                if compile_failure is not None:
                    results.append(TestResult(test_id=test.test_id, passed=False,
                                              failure_kind=compile_failure))
                    continue
                try:
                    session_type = CppScoreSession if is_cpp else CounterSession
                    async with session_type(source_dir) as session:
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
