"""Validated models for authored CodeMafia challenge content.

These models validate trusted, versioned content. They do not execute tests,
player code, or sabotage predicates. Use explicit public-response models when
content is sent to a player; never serialize a complete Challenge as a public
room payload.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


# Keep identifiers readable in authored files while preventing whitespace,
# path separators, and arbitrary strings from becoming lookup keys.
ContentId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$",
    ),
]

SemanticVersion = Annotated[
    str,
    StringConstraints(
        pattern=r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$",
        max_length=32,
    ),
]

PythonVersion = Annotated[
    str,
    StringConstraints(pattern=r"^3\.(?:\d{1,2})$", max_length=4),
]

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000)]
SourceCode = Annotated[str, StringConstraints(min_length=1, max_length=65_536)]

ChallengeCategory = Literal[
    "data-structures-algorithms",
    "object-oriented",
    "security",
    "front-end",
    "back-end",
]

TestVisibility = Literal["public", "hidden"]
ReviewStatus = Literal["draft", "reviewed", "approved"]
RuntimePolicyId = Literal["python-standard-v1"]


class ChallengeContentModel(BaseModel):
    """Shared strict configuration for authored challenge records."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )


class ChallengeFunction(ChallengeContentModel):
    """A named function or method referenced by TODOs, tests, or objectives."""

    id: ContentId
    name: ShortText
    purpose: Description


class ChallengeTodo(ChallengeContentModel):
    """A shared, player-visible repair instruction for one or more functions."""

    id: ContentId
    instructions: Description
    target_function_ids: tuple[ContentId, ...] = Field(min_length=1)


class ChallengeTest(ChallengeContentModel):
    """Metadata for one trusted runner test and its player-safe presentation."""

    id: ContentId
    test_definition_id: ContentId
    name: ShortText | None = None
    visibility: TestVisibility
    required_for_civilian_win: bool
    expected_behavior: Description
    target_function_ids: tuple[ContentId, ...] = Field(min_length=1)
    public_description: Description | None = None
    safe_failure_message: ShortText | None = None

    @model_validator(mode="after")
    def validate_visibility_fields(self) -> ChallengeTest:
        """Require display text for public tests and keep hidden details private."""

        if self.visibility == "public":
            if self.name is None:
                raise ValueError("public tests require a player-safe name")
            if self.public_description is None:
                raise ValueError("public tests require a player-safe description")
            if self.safe_failure_message is None:
                raise ValueError("public tests require a safe failure message")
        elif any(
            value is not None
            for value in (self.name, self.public_description, self.safe_failure_message)
        ):
            raise ValueError("hidden tests must not contain player-facing detail fields")

        return self


class TestRegressionVerification(ChallengeContentModel):
    """Allow-listed sabotage check: an official test passed, then later regressed."""

    kind: Literal["test_regression"]
    test_id: ContentId


class SabotageObjective(ChallengeContentModel):
    """Private objective definition; live progress belongs to match state."""

    id: ContentId
    private_description: Description
    target_function_ids: tuple[ContentId, ...] = ()
    target_test_ids: tuple[ContentId, ...] = Field(min_length=1)
    verification: TestRegressionVerification
    progress_policy: Literal["verified_once"] = "verified_once"
    completion_effect: Literal["record_completion"] = "record_completion"
    fairness_notes: Description

    @model_validator(mode="after")
    def validate_verification_target(self) -> SabotageObjective:
        """Ensure the verifier only refers to a test declared as an objective target."""

        if self.verification.test_id not in self.target_test_ids:
            raise ValueError("verification.test_id must be included in target_test_ids")

        return self


class ChallengeAuthorship(ChallengeContentModel):
    """Review provenance for one immutable challenge version."""

    authored_by: ShortText
    created_at: date
    reviewed_by: ShortText | None = None
    review_status: ReviewStatus = "draft"

    @model_validator(mode="after")
    def validate_review_provenance(self) -> ChallengeAuthorship:
        """A reviewed or approved record must identify its reviewer."""

        if self.review_status in {"reviewed", "approved"} and self.reviewed_by is None:
            raise ValueError("reviewed and approved content must identify reviewed_by")

        return self


class Challenge(ChallengeContentModel):
    """One complete, immutable challenge content document."""

    schema_version: Literal[1]
    id: ContentId
    version: SemanticVersion
    category: ChallengeCategory
    title: ShortText
    prompt: Description
    language: Literal["python"]
    python_version: PythonVersion
    starter_code: SourceCode
    functions: tuple[ChallengeFunction, ...] = Field(min_length=1)
    todos: tuple[ChallengeTodo, ...] = Field(min_length=1)
    tests: tuple[ChallengeTest, ...] = Field(min_length=1)
    runtime_policy: RuntimePolicyId
    reference_solution: SourceCode
    sabotage_objectives: tuple[SabotageObjective, ...] = Field(min_length=1)
    authorship: ChallengeAuthorship

    @field_validator("starter_code", "reference_solution")
    @classmethod
    def validate_source_is_not_blank(cls, value: str) -> str:
        """Reject empty source while preserving every character of valid code."""

        if not value.strip():
            raise ValueError("source code must contain non-whitespace characters")
        return value

    @model_validator(mode="after")
    def validate_internal_references(self) -> Challenge:
        """Reject duplicate IDs, dangling references, and unusable victory tests."""

        function_ids = self._unique_ids("functions", (item.id for item in self.functions))
        test_ids = self._unique_ids("tests", (item.id for item in self.tests))
        self._unique_ids(
            "test definitions",
            (item.test_definition_id for item in self.tests),
        )
        self._unique_ids("todos", (item.id for item in self.todos))
        self._unique_ids(
            "sabotage_objectives",
            (item.id for item in self.sabotage_objectives),
        )

        if not any(test.required_for_civilian_win for test in self.tests):
            raise ValueError("at least one test must be required for civilian victory")

        for todo in self.todos:
            self._require_references(
                owner=f"todo {todo.id}",
                references=todo.target_function_ids,
                available=function_ids,
                target_kind="function",
            )

        for test in self.tests:
            self._require_references(
                owner=f"test {test.id}",
                references=test.target_function_ids,
                available=function_ids,
                target_kind="function",
            )

        for objective in self.sabotage_objectives:
            self._require_references(
                owner=f"objective {objective.id}",
                references=objective.target_function_ids,
                available=function_ids,
                target_kind="function",
            )
            self._require_references(
                owner=f"objective {objective.id}",
                references=objective.target_test_ids,
                available=test_ids,
                target_kind="test",
            )
            self._require_references(
                owner=f"objective {objective.id} verification",
                references=(objective.verification.test_id,),
                available=test_ids,
                target_kind="test",
            )

        if self.reference_solution.strip() == self.starter_code.strip():
            raise ValueError("reference_solution must differ from starter_code")

        return self

    @staticmethod
    def _unique_ids(owner: str, identifiers: Iterable[str]) -> set[str]:
        """Return IDs as a set, rejecting duplicates within one ID namespace."""

        id_list = list(identifiers)
        id_set = set(id_list)
        if len(id_list) != len(id_set):
            raise ValueError(f"{owner} contains duplicate IDs")
        return id_set

    @staticmethod
    def _require_references(
        *,
        owner: str,
        references: tuple[str, ...],
        available: set[str],
        target_kind: str,
    ) -> None:
        """Ensure every referenced function or test exists in this challenge."""

        missing = sorted(set(references) - available)
        if missing:
            missing_text = ", ".join(missing)
            raise ValueError(f"{owner} references unknown {target_kind} ID(s): {missing_text}")
