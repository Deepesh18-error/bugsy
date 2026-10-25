"""Guest join attempts reveal no room metadata and have a storage-backed limit."""

import unittest

from app.rooms.service import RoomPolicy, RoomService, RoomServiceError


def run_immediate(coroutine):
    try:
        coroutine.send(None)
    except StopIteration as result:
        return result.value
    raise AssertionError("The fake room repository unexpectedly yielded.")


class JoinLimitRepository:
    def __init__(self):
        self.windows = {}
        self.room_lookups = 0

    async def allow_join_attempt(self, subject_hash, *, window_seconds, max_attempts):
        count = self.windows.get(subject_hash, 0) + 1
        self.windows[subject_hash] = count
        return count <= max_attempts

    async def load_room(self, room_code):
        self.room_lookups += 1
        return None


class RoomJoinSecurityTests(unittest.TestCase):
    def test_invalid_and_absent_codes_share_a_public_response(self):
        repository = JoinLimitRepository()
        service = RoomService(repository, policy=RoomPolicy(max_join_attempts=3))
        errors = []
        for code in ("invalid!", "ABCDEFG2"):
            with self.assertRaises(RoomServiceError) as caught:
                run_immediate(service.join_room(code, "Ada", join_subject="client-one"))
            errors.append((caught.exception.code, caught.exception.message,
                           caught.exception.status_code))
        self.assertEqual(errors[0], errors[1])
        self.assertEqual(errors[0], ("ROOM_UNAVAILABLE", "Room is unavailable.", 404))

    def test_room_guessing_is_limited_before_lookup_and_per_subject(self):
        repository = JoinLimitRepository()
        service = RoomService(repository, policy=RoomPolicy(max_join_attempts=2))
        for _ in range(2):
            with self.assertRaises(RoomServiceError) as caught:
                run_immediate(service.join_room("ABCDEFG2", "Ada", join_subject="client-one"))
            self.assertEqual(caught.exception.code, "ROOM_UNAVAILABLE")
        prior_lookups = repository.room_lookups
        with self.assertRaises(RoomServiceError) as caught:
            run_immediate(service.join_room("ABCDEFG2", "Ada", join_subject="client-one"))
        self.assertEqual((caught.exception.code, caught.exception.status_code), ("RATE_LIMITED", 429))
        self.assertEqual(repository.room_lookups, prior_lookups)
        with self.assertRaises(RoomServiceError) as other:
            run_immediate(service.join_room("ABCDEFG2", "Ada", join_subject="client-two"))
        self.assertEqual(other.exception.code, "ROOM_UNAVAILABLE")
        self.assertEqual(len(repository.windows), 2)


if __name__ == "__main__":
    unittest.main()
