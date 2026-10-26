"""Production must reject local defaults before accepting any guests."""

import unittest
import json
from types import SimpleNamespace

from fastapi import Response
from fastapi import HTTPException
from unittest.mock import patch

from app.config import parse_bool, validate_production_settings
from app.api.rooms import create_room
from app.api.schemas import CreateRoomRequest
from app.observability import OperationalMetrics
from app.main import operational_metrics as metrics_endpoint


GOOD = {
    "environment": "production",
    "allowed_origins": ("https://game.example.com",),
    "secure_cookie": True,
    "editor_websocket_url": "wss://game.example.com/api/rooms/editor/ws",
    "editor_service_key": "e" * 32,
    "runner_result_key": "r" * 32,
    "redis_url": "redis://redis:6379/0",
    "metrics_token": "m" * 32,
}


class ProductionConfigTests(unittest.TestCase):
    def test_valid_public_configuration(self):
        self.assertIsNone(validate_production_settings(**GOOD))
        self.assertIsNone(validate_production_settings(**{**GOOD, "environment": "staging"}))
        self.assertIsNone(validate_production_settings(**{**GOOD, "environment": "staging",
            "allow_draft_content": True}))

    def test_development_does_not_require_public_urls(self):
        self.assertIsNone(validate_production_settings(**{**GOOD, "environment": "development",
            "allowed_origins": ("http://127.0.0.1:5173",), "runner_result_key": ""}))

    def test_insecure_or_missing_values_fail_before_startup(self):
        cases = (
            {"allowed_origins": ("http://game.example.com",)},
            {"allowed_origins": ("https://game.example.com/path",)},
            {"allowed_origins": ("https://localhost:5173",)},
            {"secure_cookie": False},
            {"editor_websocket_url": "ws://game.example.com/editor"},
            {"editor_websocket_url": "wss://127.0.0.1/editor"},
            {"editor_service_key": "short"},
            {"editor_service_key": "replace-with-a-long-random-shared-secret"},
            {"runner_result_key": ""},
            {"redis_url": None},
            {"metrics_token": "short"},
            {"environment": "prodution"},
            {"allow_draft_content": True},
        )
        for change in cases:
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_production_settings(**{**GOOD, **change})

    def test_boolean_settings_reject_typos(self):
        self.assertTrue(parse_bool(" TRUE ", name="FLAG"))
        self.assertFalse(parse_bool("0", name="FLAG"))
        with self.assertRaises(ValueError):
            parse_bool("tru", name="FLAG")

    def test_maintenance_mode_blocks_room_creation(self):
        request = SimpleNamespace(headers={"origin": "https://game.example.com"},
            app=SimpleNamespace(state=SimpleNamespace(
                allowed_origins=("https://game.example.com",), accept_new_matches=False,
            )))
        coroutine = create_room(CreateRoomRequest(display_name="Ada", capacity=4), request, Response())
        try:
            coroutine.send(None)
        except StopIteration as stopped:
            result = stopped.value
        else:
            self.fail("Room creation unexpectedly called a storage service.")
        self.assertEqual(result.status_code, 503)
        self.assertEqual(json.loads(result.body)["error"]["code"], "NEW_MATCHES_PAUSED")

    def test_metrics_contain_only_fixed_aggregate_names(self):
        metrics = OperationalMetrics()
        metrics.increment("room_created")
        metrics.observe_public_event("MatchStarted", {"room_code": "SECRET"})
        metrics.observe_public_event("OfficialTestRunStatusChanged", {"status": "error", "run_id": "SECRET"})
        output = metrics.render(redis_up=False)
        self.assertIn("codemafia_room_created_total 1", output)
        self.assertIn("codemafia_match_started_total 1", output)
        self.assertIn("codemafia_runner_error_total 1", output)
        self.assertIn("codemafia_redis_up 0", output)
        self.assertNotIn("SECRET", output)
        with self.assertRaises(ValueError):
            metrics.increment("player_SECRET")

    def test_metrics_endpoint_requires_private_bearer_token(self):
        class Redis:
            async def ping(self):
                return True

        state = SimpleNamespace(redis_client=Redis(), operational_metrics=OperationalMetrics())
        request = SimpleNamespace(headers={}, app=SimpleNamespace(state=state))
        with patch("app.main.metrics_token", "t" * 32):
            with self.assertRaises(HTTPException) as denied:
                coroutine = metrics_endpoint(request)
                coroutine.send(None)
            self.assertEqual(denied.exception.status_code, 404)
            request.headers["authorization"] = "Bearer " + "t" * 32
            coroutine = metrics_endpoint(request)
            with self.assertRaises(StopIteration) as completed:
                coroutine.send(None)
        self.assertEqual(completed.exception.value.status_code, 200)
        self.assertIn(b"codemafia_redis_up 1", completed.exception.value.body)


if __name__ == "__main__":
    unittest.main()
