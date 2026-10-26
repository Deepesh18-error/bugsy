"""Allowlist of challenge digests and the exact tests their jobs may name."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

from contracts import RunnerJob
from . import oop_counter_v1 as counter
from . import collections_v1 as collections


TestFunction = Callable[[counter.CounterSession], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class TrustedTest:
    test_id: str
    definition_id: str
    required_for_civilian_win: bool
    run: TestFunction


@dataclass(frozen=True, slots=True)
class ChallengeSpec:
    challenge_id: str
    version: str
    content_digest: str
    runtime_policy: str
    tests: tuple[TrustedTest, ...]


COUNTER = ChallengeSpec(
    challenge_id="oop.counter",
    version="1.0.0",
    # Canonical digest from backend/app/challenges/loader.py. Changing the
    # authored JSON requires reviewing and intentionally updating this pin.
    content_digest="sha256:889bac261018112ba823b9f3c090b902339caf0568919f7fbc20e25c437a791a",
    runtime_policy="python-standard-v1",
    tests=(
        TrustedTest("increment-changes-count", "counter_increment_changes_count", True,
                    counter.counter_increment_changes_count),
        TrustedTest("decrement-subtracts-one", "counter_decrement_subtracts_one", True,
                    counter.counter_decrement_subtracts_one),
        TrustedTest("reset-sets-count-to-zero", "counter_reset_sets_count_to_zero", True,
                    counter.counter_reset_sets_count_to_zero),
        TrustedTest("value-returns-count", "counter_value_returns_count", True,
                    counter.counter_value_returns_count),
        TrustedTest("history-preserves-operation-order", "counter_history_preserves_operation_order", True,
                    counter.counter_history_preserves_operation_order),
    ),
)


COUNTER_1_1 = ChallengeSpec(
    challenge_id='oop.counter', version='1.1.0',
    content_digest='sha256:7bb845ee987d83f6c25614771dbf854930e9a9920716189e5289436550c76958', runtime_policy="python-standard-v1",
    tests=(
        TrustedTest('increment-changes-count', 'counter_increment_changes_count', True, counter.counter_increment_changes_count),
        TrustedTest('decrement-subtracts-one', 'counter_decrement_subtracts_one', True, counter.counter_decrement_subtracts_one),
        TrustedTest('reset-sets-count-to-zero', 'counter_reset_sets_count_to_zero', True, counter.counter_reset_sets_count_to_zero),
        TrustedTest('value-returns-count', 'counter_value_returns_count', True, counter.counter_value_returns_count),
        TrustedTest('history-preserves-operation-order', 'counter_history_preserves_operation_order', True, counter.counter_history_preserves_operation_order),
    ),
)

STACK = ChallengeSpec(
    challenge_id='oop.stack', version='1.0.0',
    content_digest='sha256:22f77171b64f0e2b22ab2d344ef66f8d855bf6d57dd798a097527dd9f475b583', runtime_policy="python-standard-v1",
    tests=(
        TrustedTest('push-size', 'oop_stack_push_size', True, collections.oop_stack_push_size),
        TrustedTest('pop-order', 'oop_stack_pop_order', True, collections.oop_stack_pop_order),
        TrustedTest('peek-preserves', 'oop_stack_peek_preserves', True, collections.oop_stack_peek_preserves),
        TrustedTest('empty-reuse', 'oop_stack_empty_reuse', True, collections.oop_stack_empty_reuse),
    ),
)

WALLET = ChallengeSpec(
    challenge_id='backend.wallet', version='1.0.0',
    content_digest='sha256:6faede3edf457ddb4e81af07bf94eb45b27861a6a7cb4b7fcfff4fe6ebe25aa5', runtime_policy="python-standard-v1",
    tests=(
        TrustedTest('deposit-balance', 'backend_wallet_deposit_balance', True, collections.backend_wallet_deposit_balance),
        TrustedTest('withdraw-bounds', 'backend_wallet_withdraw_bounds', True, collections.backend_wallet_withdraw_bounds),
        TrustedTest('statement-copy', 'backend_wallet_statement_copy', True, collections.backend_wallet_statement_copy),
        TrustedTest('invalid-amounts', 'backend_wallet_invalid_amounts', True, collections.backend_wallet_invalid_amounts),
    ),
)

_REGISTRY = {(spec.challenge_id, spec.version, spec.content_digest): spec
             for spec in (COUNTER, COUNTER_1_1, STACK, WALLET)}


def resolve_job(job: RunnerJob) -> ChallengeSpec:
    """Reject unknown content and jobs that omit or replace even a hidden test."""

    spec = _REGISTRY.get((job.challenge_id, job.challenge_version, job.challenge_content_digest))
    if spec is None or job.runtime_policy != spec.runtime_policy:
        raise ValueError("challenge content is not allowlisted for this runner")
    expected = tuple((test.test_id, test.definition_id, test.required_for_civilian_win)
                     for test in spec.tests)
    actual = tuple((test.test_id, test.test_definition_id, test.required_for_civilian_win)
                   for test in job.tests)
    if actual != expected:
        raise ValueError("job test definitions differ from the trusted registry")
    return spec
