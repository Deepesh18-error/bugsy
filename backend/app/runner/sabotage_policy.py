"""Conservative sabotage attribution; never execute submitted source here.

Credit requires a retained passing baseline and an uninterrupted chain of
impostor-authored edits. Mixed authorship, pruned history and restores fail
closed. AST comparison permits edits only inside the named target methods;
official tests independently establish bounded behavioral damage.
"""

from __future__ import annotations

import ast

from app.challenges.schema import Challenge, SabotageObjective
from app.game.models import PlayerRole, RoomState
from app.rooms.repository import EditorDocument
from app.runner.contracts import RunnerResult, TestFailureKind


def _shape(source: str, targets: set[str]) -> tuple[str, tuple[tuple[str, str], ...]] | None:
    tree = ast.parse(source)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in targets:
            found.append((node.name, ast.dump(node, include_attributes=False)))
            # Signature/decorators remain part of the surrounding shape.
            node.body = [ast.Pass()]
    if len(found) != len(targets) or {name for name, _ in found} != targets:
        return None
    return ast.dump(tree, include_attributes=False), tuple(sorted(found))


def attributable_regression(
    state: RoomState, challenge: Challenge, objective: SabotageObjective,
    document: EditorDocument | None, result: RunnerResult,
) -> bool:
    current = state.match.current_round if state.match else None
    if current is None or document is None or document.revision_id != result.source_revision_id:
        return False
    if not document.history or document.history[-1].source != document.source:
        return False
    impostor = next((p for p in state.players if p.role is PlayerRole.IMPOSTOR and p.is_alive), None)
    if impostor is None:
        return False
    target = objective.verification.test_id
    verdicts = {item.test_id: item for item in result.tests}
    if target not in verdicts or verdicts[target].passed:
        return False
    if any(not item.passed and item.failure_kind is not TestFailureKind.ASSERTION for item in result.tests):
        return False  # crashes, malformed programs and timeouts never earn credit
    history = document.history
    by_id = {item.revision_id: index for index, item in enumerate(history)}
    targets = set(objective.target_function_ids)
    names = {item.name for item in challenge.functions if item.id in targets}
    if not names:
        return False
    # Tests exercising the changed method can legitimately regress together.
    affected = {test.id for test in challenge.tests if targets.intersection(test.target_function_ids)}
    for baseline in reversed(current.official_test_history):
        if target not in baseline.passed_test_ids or baseline.completed_at >= result.completed_at:
            continue
        index = by_id.get(baseline.source_revision_id)
        if index is None or index == len(history) - 1:
            continue
        changes = history[index + 1:]
        if any(item.author_player_id != impostor.player_id or item.restored_from_revision_id is not None
               or item.recorded_at < baseline.completed_at for item in changes):
            continue
        # No new failure outside the affected methods, and no simultaneous
        # repair to disguise an unrelated harmful change.
        passed = {item.test_id for item in result.tests if item.passed}
        if not (set(baseline.passed_test_ids) - passed) <= affected:
            continue
        if not passed <= set(baseline.passed_test_ids):
            continue
        try:
            before = _shape(history[index].source, names)
            after = _shape(document.source, names)
        except (SyntaxError, ValueError, RecursionError):
            continue
        if before and after and before[0] == after[0] and before[1] != after[1]:
            return True
    return False
