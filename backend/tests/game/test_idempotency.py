"""Request retry deduplication and request-ID reuse policy."""

import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from app.game.commands import SetReady
from app.game.idempotency import RequestIdempotencyStore, apply_command_idempotently
from app.game.outcomes import RejectionCode, TransitionAccepted, TransitionRejected
from app.game.transitions import apply_command

from _builders import NOW, make_lobby


class IdempotencyTests(unittest.TestCase):
    def test_same_request_replays_original_transition_instead_of_applying_again(self) -> None:
        store = RequestIdempotencyStore()
        state = make_lobby()
        command = SetReady(request_id="retry-ready", player_id="p2", ready=True)

        first = apply_command_idempotently(store, state, command, NOW, monotonic_now=1)
        retry = apply_command_idempotently(
            store, first.outcome.state, command, NOW, monotonic_now=2
        )

        self.assertIsInstance(first.outcome, TransitionAccepted)
        self.assertFalse(first.replayed)
        self.assertTrue(retry.replayed)
        self.assertEqual(retry.outcome, first.outcome)

    def test_same_request_id_with_different_payload_is_rejected(self) -> None:
        store = RequestIdempotencyStore()
        state = make_lobby()
        original = SetReady(request_id="reused-id", player_id="p2", ready=True)
        different = SetReady(request_id="reused-id", player_id="p2", ready=False)
        first = apply_command_idempotently(store, state, original, NOW, monotonic_now=1)

        result = apply_command_idempotently(
            store, first.outcome.state, different, NOW, monotonic_now=2
        )

        self.assertIsInstance(result.outcome, TransitionRejected)
        self.assertEqual(result.outcome.code, RejectionCode.DUPLICATE_REQUEST)
        self.assertFalse(result.replayed)

    def test_distinct_request_ids_are_distinct_operations(self) -> None:
        store = RequestIdempotencyStore()
        state = make_lobby()
        set_ready = SetReady(request_id="ready-on", player_id="p2", ready=True)
        unset_ready = SetReady(request_id="ready-off", player_id="p2", ready=False)

        first = apply_command_idempotently(store, state, set_ready, NOW, monotonic_now=1)
        second = apply_command_idempotently(
            store, first.outcome.state, unset_ready, NOW, monotonic_now=2
        )

        self.assertIsInstance(second.outcome, TransitionAccepted)
        self.assertFalse(second.replayed)
        self.assertFalse(second.outcome.state.players[1].is_ready)

    def test_expired_request_can_be_processed_again_after_retention(self) -> None:
        store = RequestIdempotencyStore(ttl_seconds=10)
        state = make_lobby()
        command = SetReady(request_id="expires", player_id="p2", ready=True)
        first = apply_command_idempotently(store, state, command, NOW, monotonic_now=0)

        after_expiry = apply_command_idempotently(
            store, state, command, NOW, monotonic_now=11
        )

        self.assertFalse(first.replayed)
        self.assertFalse(after_expiry.replayed)
        self.assertIsInstance(after_expiry.outcome, TransitionAccepted)

    def test_two_concurrent_retries_execute_the_transition_once(self) -> None:
        store = RequestIdempotencyStore()
        state = make_lobby()
        command = SetReady(request_id="concurrent-ready", player_id="p2", ready=True)
        operation_started = Event()
        allow_operation_to_finish = Event()
        invocation_count = 0

        def operation():
            nonlocal invocation_count
            invocation_count += 1
            operation_started.set()
            if not allow_operation_to_finish.wait(timeout=3):
                raise TimeoutError("test did not release the first operation")
            return apply_command(state, command, NOW)

        with ThreadPoolExecutor(max_workers=2) as executor:
            first_future = executor.submit(
                store.execute, state, command, operation, monotonic_now=1
            )
            self.assertTrue(operation_started.wait(timeout=3))
            second_future = executor.submit(
                store.execute, state, command, operation, monotonic_now=1
            )
            allow_operation_to_finish.set()
            first = first_future.result(timeout=3)
            second = second_future.result(timeout=3)

        self.assertEqual(invocation_count, 1)
        self.assertEqual(sum(result.replayed for result in (first, second)), 1)
        self.assertEqual(first.outcome, second.outcome)


if __name__ == "__main__":
    unittest.main()
