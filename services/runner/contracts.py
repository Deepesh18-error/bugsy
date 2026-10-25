"""Independent, strict copy of the API's version 1 runner wire contract."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
import hmac
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


PROTOCOL_VERSION = 1
MAX_SOURCE_BYTES = 65_536
MAX_JOB_BYTES = 160_000
MAX_RESULT_BYTES = 32_000
MAX_TESTS = 64
Token = Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")]
Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$", max_length=71)]


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class RunnerStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    TIMED_OUT = "timed_out"
    RESOURCE_LIMIT = "resource_limit"
    POLICY_VIOLATION = "policy_violation"
    RUNNER_ERROR = "runner_error"
    CANCELLED = "cancelled"


class TestFailureKind(StrEnum):
    ASSERTION = "assertion"
    EXCEPTION = "exception"
    TIMEOUT = "timeout"


class TestCase(WireModel):
    test_id: Token
    test_definition_id: Token
    required_for_civilian_win: bool


class RunnerJob(WireModel):
    protocol_version: Literal[PROTOCOL_VERSION] = PROTOCOL_VERSION
    run_id: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]
    room_code: Annotated[str, StringConstraints(min_length=4, max_length=32, pattern=r"^[A-Z0-9]+$")]
    match_id: Token
    round_number: int = Field(ge=1, le=4)
    deadline_id: Token
    challenge_id: Token
    challenge_version: Annotated[str, StringConstraints(pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$", max_length=32)]
    challenge_content_digest: Digest
    runtime_policy: Literal["python-standard-v1"]
    source_revision_id: Token
    source: str = Field(min_length=1, max_length=MAX_SOURCE_BYTES)
    requested_by_player_id: Token
    request_id: Token
    requested_at: datetime
    tests: tuple[TestCase, ...] = Field(min_length=1, max_length=MAX_TESTS)
    dedupe_key: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

    @field_validator("source")
    @classmethod
    def source_byte_limit(cls, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise ValueError("source exceeds the byte limit")
        return value

    @model_validator(mode="after")
    def validate_job(self) -> RunnerJob:
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() != timedelta(0):
            raise ValueError("requested_at must be UTC")
        if len({test.test_id for test in self.tests}) != len(self.tests):
            raise ValueError("duplicate test IDs")
        if len({test.test_definition_id for test in self.tests}) != len(self.tests):
            raise ValueError("duplicate test definition IDs")
        if not any(test.required_for_civilian_win for test in self.tests):
            raise ValueError("a required test is needed")
        return self


class TestResult(WireModel):
    test_id: Token
    passed: bool
    failure_kind: TestFailureKind | None = None

    @model_validator(mode="after")
    def validate_failure(self) -> TestResult:
        if self.passed == (self.failure_kind is not None):
            raise ValueError("test failure shape is inconsistent")
        return self


class RunnerResult(WireModel):
    protocol_version: Literal[PROTOCOL_VERSION] = PROTOCOL_VERSION
    run_id: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]
    room_code: Annotated[str, StringConstraints(min_length=4, max_length=32, pattern=r"^[A-Z0-9]+$")]
    match_id: Token
    round_number: int = Field(ge=1, le=4)
    deadline_id: Token
    challenge_id: Token
    challenge_version: Annotated[str, StringConstraints(pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$", max_length=32)]
    challenge_content_digest: Digest
    source_revision_id: Token
    status: RunnerStatus
    started_at: datetime
    completed_at: datetime
    tests: tuple[TestResult, ...] = Field(max_length=MAX_TESTS)
    signature: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

    @model_validator(mode="after")
    def validate_result(self) -> RunnerResult:
        if any(t.tzinfo is None or t.utcoffset() != timedelta(0) for t in (self.started_at, self.completed_at)):
            raise ValueError("result timestamps must be UTC")
        if self.completed_at < self.started_at:
            raise ValueError("completion precedes start")
        if len({test.test_id for test in self.tests}) != len(self.tests):
            raise ValueError("duplicate test result IDs")
        if self.status is RunnerStatus.COMPLETED and not self.tests:
            raise ValueError("completed results require test verdicts")
        if self.status is not RunnerStatus.COMPLETED and self.tests:
            raise ValueError("infrastructure results cannot include test verdicts")
        if self.status is RunnerStatus.RUNNING and self.started_at != self.completed_at:
            raise ValueError("running status timestamps must identify the start instant")
        return self


def decode_job(raw: bytes) -> RunnerJob:
    if not raw or len(raw) > MAX_JOB_BYTES:
        raise ValueError("invalid runner job size")
    return RunnerJob.model_validate_json(raw)


def make_signed_result(
    job: RunnerJob,
    *,
    status: RunnerStatus,
    started_at: datetime,
    completed_at: datetime,
    tests: tuple[TestResult, ...],
    signing_key: str,
) -> bytes:
    if len(signing_key.encode("utf-8")) < 32:
        raise ValueError("runner signing key must be at least 32 bytes")
    result = RunnerResult(
        run_id=job.run_id, room_code=job.room_code, match_id=job.match_id,
        round_number=job.round_number, deadline_id=job.deadline_id,
        challenge_id=job.challenge_id, challenge_version=job.challenge_version,
        challenge_content_digest=job.challenge_content_digest,
        source_revision_id=job.source_revision_id, status=status,
        started_at=started_at, completed_at=completed_at, tests=tests,
        signature="0" * 64,
    )
    canonical = json.dumps(result.model_dump(mode="json", exclude={"signature"}), sort_keys=True,
                           separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    signature = hmac.new(signing_key.encode("utf-8"), canonical, sha256).hexdigest()
    raw = json.dumps(result.model_copy(update={"signature": signature}).model_dump(mode="json"),
                     sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(raw) > MAX_RESULT_BYTES:
        raise ValueError("signed result exceeds the size limit")
    return raw
