"""Only authenticated, live players receive the advisory public bundle."""

from __future__ import annotations

from dataclasses import replace
import json
from types import SimpleNamespace
import unittest

from starlette.requests import Request

from app.api.feedback import FeedbackRequest, public_feedback_bundle
from app.api.rooms import COOKIE_NAME
from app.game.models import GamePhase
from app.rooms.service import AuthenticatedGuest, RoomServiceError
from runner_support import LOADED, coding_room, run_immediate


class FakeGuestService:
    def __init__(self, state, *, reject=False):
        self.state = state
        self.reject = reject

    async def authenticate_player(self, credential):
        if self.reject or credential != "test-credential":
            raise RoomServiceError("SESSION_INVALID", "Session is invalid.", 401)
        return AuthenticatedGuest(self.state, "player-1", self.state.expires_at)


def request(state, *, reject=False):
    app = SimpleNamespace(state=SimpleNamespace(
        room_service=FakeGuestService(state, reject=reject),
        allowed_origins=("http://localhost:5173",),
    ))
    return Request({
        "type": "http", "method": "POST", "path": "/api/rooms/feedback/bundle",
        "headers": [(b"origin", b"http://localhost:5173"),
                    (b"cookie", f"{COOKIE_NAME}=test-credential".encode())],
        "app": app,
    })


class PublicFeedbackTests(unittest.TestCase):
    def test_bundle_contains_public_cases_only(self):
        response = run_immediate(public_feedback_bundle(
            FeedbackRequest(room_code="TEST42", round_number=1), request(coding_room()),
        ))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body)
        self.assertTrue(payload["provisional_only"])
        self.assertEqual(payload["source_revision_id"], "revision-1")
        self.assertEqual({item["test_id"] for item in payload["tests"]},
                         {item.id for item in LOADED.challenge.tests if item.visibility == "public"})
        self.assertNotIn("reference_solution", response.body.decode())
        for item in LOADED.challenge.tests:
            if item.visibility == "hidden":
                self.assertNotIn(item.id, response.body.decode())

    def test_expired_phase_and_invalid_guest_get_no_bundle(self):
        state = coding_room()
        wrong_phase = replace(state, phase=GamePhase.ROUND_RESULT, phase_deadline=None)
        response = run_immediate(public_feedback_bundle(
            FeedbackRequest(room_code="TEST42", round_number=1), request(wrong_phase),
        ))
        self.assertEqual(response.status_code, 409)
        denied = run_immediate(public_feedback_bundle(
            FeedbackRequest(room_code="TEST42", round_number=1), request(state, reject=True),
        ))
        self.assertEqual(denied.status_code, 401)


if __name__ == "__main__":
    unittest.main()
