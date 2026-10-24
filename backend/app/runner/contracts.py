"""Versioned, size-bounded contracts shared with the runner supervisor."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


PROTOCOL_VERSION = 1
MAX_SOURCE_BYTES = 65_536
MAX_TESTS = 64
MAX_JOB_BYTES = 160_000
MAX_RESULT_BYTES = 32_000
MAX_RESULT_TTL_SECONDS = 3_600
Token = Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")]
Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$", max_length=71)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RunnerStatus(StrEnum):
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


class RunnerTestCase(StrictModel):
    test_id: Token
    test_definition_id: Token
    required_for_civilian_win: bool


class RunnerJob(StrictModel):
    protocol_version: Literal[PROTOCOL_VERSION] = PROTOCOL_VERSION
    run_id: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$", max_length=32)]
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
    tests: tuple[RunnerTestCase, ...] = Field(min_length=1, max_length=MAX_TESTS)
    dedupe_key: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$", max_length=64)]

    @field_validator("source")
    @classmethod
    def source_is_utf8_bounded(cls, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise ValueError("source exceeds the byte limit")
        return value

    @field_validator("requested_at")
    @classmethod
    def request_time_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("requested_at must use UTC")
        return value

    @model_validator(mode="after")
    def test_identifiers_are_unique(self) -> RunnerJob:
        ids = [test.test_id for test in self.tests]
        definitions = [test.test_definition_id for test in self.tests]
        if len(ids) != len(set(ids)) or len(definitions) != len(set(definitions)):
            raise ValueError("runner test identities must be unique")
        return self


class RunnerTestResult(StrictModel):
    test_id: Token
    passed: bool
    failure_kind: TestFailureKind | None = None

    @model_validator(mode="after")
    def failure_shape_matches(self) -> RunnerTestResult:
        if self.passed and self.failure_kind is not None:
            raise ValueError("passed tests cannot contain a failure kind")
        if not self.passed and self.failure_kind is None:
            raise ValueError("failed tests require a failure kind")
        return self


class RunnerResult(StrictModel):
    protocol_version: Literal[PROTOCOL_VERSION] = PROTOCOL_VERSION
    run_id: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$", max_length=32)]
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
    tests: tuple[RunnerTestResult, ...] = Field(max_length=MAX_TESTS)
    signature: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$", max_length=64)]

    @model_validator(mode="after")
    def validate_completion(self) -> RunnerResult:
        for value in (self.started_at, self.completed_at):
            if value.tzinfo is None or value.utcoffset() != timedelta(0):
                raise ValueError("runner timestamps must use UTC")
        if self.completed_at < self.started_at:
            raise ValueError("runner completion precedes start")
        ids = [item.test_id for item in self.tests]
        if len(ids) != len(set(ids)):
            raise ValueError("runner results contain duplicate test IDs")
        if self.status is RunnerStatus.COMPLETED and not self.tests:
            raise ValueError("completed runs must include test results")
        if self.status is not RunnerStatus.COMPLETED and self.tests:
            raise ValueError("infrastructure failures cannot contain test verdicts")
        return self


class RunnerQueueState(StrEnum):
    ENQUEUED = "enqueued"
    DEDUPLICATED = "deduplicated"
    FULL = "full"


class RunnerEnqueueReceipt(StrictModel):
    state: RunnerQueueState
    run_id: str | None = None
    stream_id: str | None = None

    @model_validator(mode="after")
    def validate_receipt_shape(self) -> RunnerEnqueueReceipt:
        if self.state is RunnerQueueState.FULL:
            if self.run_id is not None or self.stream_id is not None:
                raise ValueError("full queue receipts cannot identify a run")
        elif self.state is RunnerQueueState.ENQUEUED:
            if self.run_id is None or self.stream_id is None:
                raise ValueError("enqueued receipts require a run and stream ID")
        elif self.state is RunnerQueueState.DEDUPLICATED:
            if self.run_id is None or self.stream_id is not None:
                raise ValueError("deduplicated receipts require only the original run ID")
        return self


def canonical_result_bytes(result: RunnerResult) -> bytes:
    payload = result.model_dump(mode="json", exclude={"signature"})
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sign_result(result_without_signature: dict[str, object], secret: str) -> str:
    if len(secret.encode("utf-8")) < 32:
        raise ValueError("runner result signing key must be at least 32 bytes")
    raw = json.dumps(result_without_signature, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()


def verify_result_signature(result: RunnerResult, secret: str) -> bool:
    if len(secret.encode("utf-8")) < 32 or re.fullmatch(r"[0-9a-f]{64}", result.signature) is None:
        return False
    expected = hmac.new(secret.encode("utf-8"), canonical_result_bytes(result), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, result.signature)


def encode_model(model: BaseModel, *, maximum_bytes: int) -> bytes:
    raw = json.dumps(model.model_dump(mode="json"), sort_keys=True,
                     separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(raw) > maximum_bytes:
        raise ValueError("runner message exceeds its size limit")
    return raw
