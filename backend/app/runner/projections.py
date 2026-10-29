"""Player-safe result summaries; never expose runner diagnostics or hidden tests."""

from __future__ import annotations

from app.challenges.schema import Challenge
from app.runner.contracts import RunnerResult, RunnerStatus, TestFailureKind


def player_safe_result_payload(challenge: Challenge, result: RunnerResult) -> dict[str, object]:
    """Project only public test names, pass/fail states, and authored safe copy."""

    if result.status is not RunnerStatus.COMPLETED:
        return {
            "run_id": result.run_id,
            "source_revision_id": result.source_revision_id,
            "status": "unavailable",
            "message": "Official tests could not finish. You can retry on this revision.",
            "tests": [],
        }
    outcomes = {item.test_id: item.passed for item in result.tests}
    compile_error = challenge.language == "cpp" and any(
        item.failure_kind is TestFailureKind.COMPILE_ERROR for item in result.tests
    )
    public_tests = []
    for test in challenge.tests:
        if test.visibility != "public":
            continue
        passed = outcomes[test.id]
        public_tests.append({
            "test_id": test.id,
            "name": test.name,
            "passed": passed,
            "required_for_civilian_win": test.required_for_civilian_win,
            "message": None if passed else (
                "C++ did not compile. Check syntax and the required function names and parameters."
                if compile_error else test.safe_failure_message
            ),
        })
    return {
        "run_id": result.run_id,
        "source_revision_id": result.source_revision_id,
        "status": "completed",
        "all_required_tests_passed": all(
            outcomes[test.id]
            for test in challenge.tests
            if test.required_for_civilian_win
        ),
        "tests": public_tests,
    }
