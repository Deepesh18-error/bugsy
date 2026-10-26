"""Authenticated public-test bundle for optional, explicitly provisional feedback."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.rooms import COOKIE_NAME, _require_allowed_origin
from app.challenges.loader import ChallengeLoadError, load_challenge
from app.game.models import ConnectionStatus, GamePhase
from app.rooms.repository import RoomStorageError
from app.rooms.service import RoomServiceError


router = APIRouter(prefix="/api/rooms/feedback", tags=["feedback"])

# This deliberately small browser bundle is kept separate from the trusted
# runner. It is public, advisory code and never participates in match wins.
_PUBLIC_TEST_CODE = {
    "counter_increment_changes_count": (
        "counter = Counter()\n"
        "counter.increment()\n"
        "assert counter.count == 1 and counter.history == ['inc']"
    ),
    "counter_decrement_subtracts_one": (
        "counter = Counter()\n"
        "counter.decrement()\n"
        "assert counter.count == -1 and counter.history == ['dec']"
    ),
    "counter_reset_sets_count_to_zero": (
        "counter = Counter()\n"
        "counter.increment()\n"
        "counter.reset()\n"
        "assert counter.count == 0 and counter.history == ['inc', 'reset']"
    ),
    "counter_value_returns_count": (
        "counter = Counter()\n"
        "counter.count = 7\n"
        "assert counter.value() == 7"
    ),
    'oop_stack_push_size': 's = Stack()\ns.push(7)\ns.push(0)\nassert s.size() == 2',
    'oop_stack_pop_order': 's = Stack()\ns.push(3)\ns.push(8)\nassert s.pop() == 8 and s.pop() == 3 and s.size() == 0',
    'oop_stack_peek_preserves': 's = Stack()\ns.push(4)\nassert s.peek() == 4 and s.peek() == 4 and s.size() == 1',
    'backend_wallet_deposit_balance': 'w = Wallet()\nassert w.deposit(125) is True\nassert w.balance == 125 and w.history == [125]',
    'backend_wallet_withdraw_bounds': 'w = Wallet()\nw.deposit(100)\nassert w.withdraw(101) is False\nassert w.balance == 100\nassert w.withdraw(100) is True and w.balance == 0',
    'backend_wallet_statement_copy': 'w = Wallet()\nw.deposit(37)\ns = w.statement()\nassert s == [37]\ns.append(99)\nassert w.history == [37]',
}


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    room_code: str = Field(min_length=4, max_length=32, pattern=r"^[A-Z0-9]+$")
    round_number: int = Field(ge=1, le=4)


def _error(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message}},
        status_code=status,
        headers={"Cache-Control": "no-store"},
    )


@router.post("/bundle")
async def public_feedback_bundle(payload: FeedbackRequest, request: Request):
    """Return player-safe public cases, never a reference solution or hidden test."""

    try:
        _require_allowed_origin(request)
        guest = await request.app.state.room_service.authenticate_player(
            request.cookies.get(COOKIE_NAME)
        )
        state = guest.state
        match = state.match
        current = match.current_round if match else None
        player = next((item for item in state.players if item.player_id == guest.player_id), None)
        if (
            state.room_code != payload.room_code
            or state.phase is not GamePhase.CODING_ROUND
            or current is None
            or current.number != payload.round_number
            or player is None
            or player.connection is ConnectionStatus.DEPARTED
            or not player.is_alive
            or datetime.now(timezone.utc) >= current.deadline.due_at
        ):
            return _error("FEEDBACK_UNAVAILABLE", "Public feedback is unavailable for this round.", 409)
        loaded = load_challenge(current.challenge_id, current.challenge_version)
        if loaded.content_digest != current.challenge_content_digest:
            return _error("CHALLENGE_CHANGED", "The pinned challenge is unavailable.", 409)

        # These are only explanatory case definitions. Browser/Pyodide results
        # are provisional and cannot be submitted to the official game engine.
        cases = [
            {
                "test_id": test.id,
                "test_definition_id": test.test_definition_id,
                "name": test.name,
                "description": test.public_description,
                "required_for_civilian_win": test.required_for_civilian_win,
                "failure_message": test.safe_failure_message,
                "test_code": _PUBLIC_TEST_CODE.get(test.test_definition_id),
            }
            for test in loaded.challenge.tests
            if test.visibility == "public"
        ]
        # An unknown test definition must not be presented as executable
        # feedback; author its public browser case before enabling the bundle.
        if any(case["test_code"] is None for case in cases):
            return _error("FEEDBACK_UNAVAILABLE", "Public feedback is not authored for this challenge yet.", 503)
        return JSONResponse(
            {
                "challenge_id": loaded.challenge.id,
                "challenge_version": loaded.challenge.version,
                "source_revision_id": current.current_source_revision_id,
                "provisional_only": True,
                "tests": cases,
            },
            headers={"Cache-Control": "no-store"},
        )
    except RoomServiceError as exc:
        return _error(exc.code, exc.message, exc.status_code)
    except RoomStorageError:
        return _error("STORAGE_UNAVAILABLE", "Feedback service is unavailable.", 503)
    except ChallengeLoadError:
        return _error("CHALLENGE_UNAVAILABLE", "The pinned challenge is unavailable.", 503)
