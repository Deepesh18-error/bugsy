"""Versioned JSON storage for the trusted, complete RoomState aggregate."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from typing import Any

from app.game.models import (
    ConnectionStatus,
    DeadlineKind,
    GameDeadline,
    GamePhase,
    MatchEndReason,
    MatchResult,
    MatchState,
    MatchWinner,
    ObjectiveStatus,
    OfficialTestResult,
    PlayerRole,
    PlayerState,
    RoomState,
    RoundState,
    SabotageObjectiveProgress,
    Vote,
    VoteKind,
)
from app.rooms.repository import RoomStorageError


STORAGE_VERSION = 1
MAX_ROOM_BYTES = 1_048_576


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Unsupported room-storage value: {type(value).__name__}")


def serialize_room(state: RoomState) -> bytes:
    payload = {"storage_version": STORAGE_VERSION, "room": asdict(state)}
    encoded = json.dumps(
        payload, default=_json_default, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    if len(encoded) > MAX_ROOM_BYTES:
        raise RoomStorageError("The room state exceeds the storage size limit.")
    return encoded


def _date(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _deadline(value: dict[str, Any] | None) -> GameDeadline | None:
    if value is None:
        return None
    return GameDeadline(
        deadline_id=value["deadline_id"],
        kind=DeadlineKind(value["kind"]),
        due_at=_date(value["due_at"]),
    )


def _player(value: dict[str, Any]) -> PlayerState:
    return PlayerState(
        player_id=value["player_id"],
        display_name=value["display_name"],
        joined_at=_date(value["joined_at"]),
        connection=ConnectionStatus(value["connection"]),
        is_ready=value["is_ready"],
        is_alive=value["is_alive"],
        role=PlayerRole(value["role"]) if value["role"] is not None else None,
        emergency_meetings_used=value["emergency_meetings_used"],
        reconnect_deadline=_deadline(value.get("reconnect_deadline")),
    )


def _vote(value: dict[str, Any]) -> Vote:
    return Vote(
        kind=VoteKind(value["kind"]),
        voter_id=value["voter_id"],
        target_id=value["target_id"],
        request_id=value["request_id"],
        cast_at=_date(value["cast_at"]),
    )


def _objective(value: dict[str, Any]) -> SabotageObjectiveProgress:
    return SabotageObjectiveProgress(
        objective_id=value["objective_id"],
        status=ObjectiveStatus(value["status"]),
        verified_revision_id=value["verified_revision_id"],
        completed_at=_date(value["completed_at"]) if value["completed_at"] else None,
    )


def _official_result(value: dict[str, Any] | None) -> OfficialTestResult | None:
    if value is None:
        return None
    return OfficialTestResult(
        run_id=value["run_id"],
        source_revision_id=value["source_revision_id"],
        completed_at=_date(value["completed_at"]),
        passed_test_ids=tuple(value["passed_test_ids"]),
        failed_test_ids=tuple(value["failed_test_ids"]),
        all_required_tests_passed=value["all_required_tests_passed"],
    )


def _round(value: dict[str, Any] | None) -> RoundState | None:
    if value is None:
        return None
    deadline = _deadline(value["deadline"])
    if deadline is None:
        raise ValueError("A stored round requires a deadline.")
    return RoundState(
        number=value["number"],
        category_id=value["category_id"],
        challenge_id=value["challenge_id"],
        challenge_version=value["challenge_version"],
        challenge_content_digest=value["challenge_content_digest"],
        started_at=_date(value["started_at"]),
        deadline=deadline,
        current_source_revision_id=value["current_source_revision_id"],
        official_test_result=_official_result(value["official_test_result"]),
        sabotage_objectives=tuple(_objective(item) for item in value["sabotage_objectives"]),
    )


def _result(value: dict[str, Any] | None) -> MatchResult | None:
    if value is None:
        return None
    return MatchResult(
        winner=MatchWinner(value["winner"]),
        reason=MatchEndReason(value["reason"]),
        round_number=value["round_number"],
        ended_at=_date(value["ended_at"]),
    )


def _match(value: dict[str, Any] | None) -> MatchState | None:
    if value is None:
        return None
    return MatchState(
        round_number=value["round_number"],
        selected_category_id=value["selected_category_id"],
        category_votes=tuple(_vote(item) for item in value["category_votes"]),
        player_votes=tuple(_vote(item) for item in value["player_votes"]),
        current_round=_round(value["current_round"]),
        result=_result(value["result"]),
        meeting_started_at=(
            _date(value["meeting_started_at"]) if value["meeting_started_at"] else None
        ),
        paused_round_deadline=_deadline(value["paused_round_deadline"]),
        meeting_cooldown_until=(
            _date(value["meeting_cooldown_until"]) if value["meeting_cooldown_until"] else None
        ),
        rematch_requests=tuple(value["rematch_requests"]),
    )


def deserialize_room(raw: bytes) -> RoomState:
    """Reject unknown storage versions instead of guessing at changed fields."""

    try:
        if len(raw) > MAX_ROOM_BYTES:
            raise ValueError("Stored room exceeds the size limit.")
        payload = json.loads(raw)
        if payload["storage_version"] != STORAGE_VERSION:
            raise ValueError("Unsupported room storage version.")
        value = payload["room"]
        return RoomState(
            room_code=value["room_code"],
            host_player_id=value["host_player_id"],
            players=tuple(_player(item) for item in value["players"]),
            created_at=_date(value["created_at"]),
            expires_at=_date(value["expires_at"]),
            phase=GamePhase(value["phase"]),
            capacity=value["capacity"],
            phase_deadline=_deadline(value["phase_deadline"]),
            match=_match(value["match"]),
            is_closed=value["is_closed"],
        )
    except (KeyError, TypeError, ValueError, UnicodeDecodeError) as exc:
        raise RoomStorageError("Stored room data is invalid or incompatible.") from exc
