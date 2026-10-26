"""Versioned JSON storage for the trusted, complete RoomState aggregate."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from typing import Any

from app.game.idempotency import MAX_LEGACY_EMBEDDED_RECEIPTS
from app.game.models import (
    ConnectionStatus,
    ChatMessageRecord,
    DeadlineKind,
    GameDeadline,
    GamePhase,
    MatchEndReason,
    MatchResult,
    MatchState,
    MatchWinner,
    ObjectiveStatus,
    OfficialRunProgress,
    OfficialRunStatus,
    OfficialTestResult,
    PlayerRole,
    PlayerState,
    RoundEndReason,
    RoomState,
    RoundState,
    SabotageObjectiveProgress,
    TestPassEvidence,
    Vote,
    VoteKind,
    VoteResolution,
)
from app.rooms.repository import (
    CommandReceipt, EditorDocument, EditorRevision, EditorStorageLimitError, MAX_EDITOR_HISTORY_BYTES,
    MAX_EDITOR_HISTORY_ENTRIES, RoomStorageError,
)


STORAGE_VERSION = 7
LEGACY_STORAGE_VERSION = 1
PREVIOUS_STORAGE_VERSION = 4
OLDER_STORAGE_VERSION = 3
INTERMEDIATE_STORAGE_VERSION = 2
SUPPORTED_STORAGE_VERSIONS = (
    LEGACY_STORAGE_VERSION,
    INTERMEDIATE_STORAGE_VERSION,
    OLDER_STORAGE_VERSION,
    PREVIOUS_STORAGE_VERSION,
    5,
    6,
    STORAGE_VERSION,
)
MAX_ROOM_BYTES = 1_048_576
EDITOR_STORAGE_VERSION = 1
MAX_EDITOR_RECORD_BYTES = 1_572_864
MAX_LEGACY_EDITOR_RECORD_BYTES = 3_145_728


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Unsupported room-storage value: {type(value).__name__}")


def serialize_room(
    state: RoomState, *, sequence: int = 0, receipts: tuple[CommandReceipt, ...] = ()
) -> bytes:
    if type(sequence) is not int or sequence < 0:
        raise ValueError("Room sequence must be non-negative.")
    if len(receipts) > MAX_LEGACY_EMBEDDED_RECEIPTS:
        raise ValueError("Too many legacy request receipts.")
    if any(item.sequence > sequence for item in receipts):
        raise ValueError("Receipt sequence cannot exceed the room sequence.")
    keys = [(item.player_id, item.request_id) for item in receipts]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate request receipts are not allowed.")
    payload = {
        "storage_version": STORAGE_VERSION,
        "room": asdict(state),
        "sequence": sequence,
        "receipts": [asdict(item) for item in receipts],
    }
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


def _chat_message(value: dict[str, Any]) -> ChatMessageRecord:
    return ChatMessageRecord(
        message_id=value["message_id"],
        player_id=value["player_id"],
        display_name=value["display_name"],
        message=value["message"],
        sent_at=_date(value["sent_at"]),
    )


def _vote(value: dict[str, Any]) -> Vote:
    return Vote(
        kind=VoteKind(value["kind"]),
        voter_id=value["voter_id"],
        target_id=value["target_id"],
        request_id=value["request_id"],
        cast_at=_date(value["cast_at"]),
    )


def _vote_resolution(value: dict[str, Any] | None) -> VoteResolution | None:
    if value is None:
        return None
    return VoteResolution(
        vote_counts=tuple((item[0], item[1]) for item in value["vote_counts"]),
        skip_count=value["skip_count"],
        ejected_player_id=value["ejected_player_id"],
        was_tie=value["was_tie"],
        resolved_at=_date(value["resolved_at"]),
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


def _test_pass_evidence(value: dict[str, Any]) -> TestPassEvidence:
    return TestPassEvidence(
        test_id=value["test_id"],
        source_revision_id=value["source_revision_id"],
        run_id=value["run_id"],
        completed_at=_date(value["completed_at"]),
    )


def _official_run_progress(value: dict[str, Any]) -> OfficialRunProgress:
    return OfficialRunProgress(
        run_id=value["run_id"],
        source_revision_id=value["source_revision_id"],
        requested_by_player_id=value["requested_by_player_id"],
        requested_at=_date(value["requested_at"]),
        updated_at=_date(value["updated_at"]),
        status=OfficialRunStatus(value["status"]),
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
        official_test_history=tuple(
            _official_result(item) for item in value.get("official_test_history", [])
        ),
        official_run_progress=tuple(
            _official_run_progress(item) for item in value.get("official_run_progress", [])
        ),
        test_pass_evidence=tuple(
            _test_pass_evidence(item) for item in value.get("test_pass_evidence", [])
        ),
        sabotage_objectives=tuple(_objective(item) for item in value["sabotage_objectives"]),
        ended_at=_date(value["ended_at"]) if value.get("ended_at") else None,
        end_reason=(
            RoundEndReason(value["end_reason"]) if value.get("end_reason") else None
        ),
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
        match_id=value.get("match_id"),
        round_number=value["round_number"],
        selected_category_id=value["selected_category_id"],
        category_votes=tuple(_vote(item) for item in value["category_votes"]),
        player_votes=tuple(_vote(item) for item in value["player_votes"]),
        last_vote_result=_vote_resolution(value.get("last_vote_result")),
        round_history=tuple(_round(item) for item in value.get("round_history", [])),
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
        sabotage_credits_used=value.get("sabotage_credits_used", 0),
        sabotage_cooldown_until=_date(value["sabotage_cooldown_until"]) if value.get("sabotage_cooldown_until") else None,
    )


def deserialize_room(raw: bytes) -> RoomState:
    """Reject unknown storage versions instead of guessing at changed fields."""

    try:
        if len(raw) > MAX_ROOM_BYTES:
            raise ValueError("Stored room exceeds the size limit.")
        payload = json.loads(raw)
        if type(payload["storage_version"]) is not int or payload["storage_version"] not in SUPPORTED_STORAGE_VERSIONS:
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
            chat_messages=tuple(_chat_message(item) for item in value.get("chat_messages", [])),
            is_closed=value["is_closed"],
        )
    except (KeyError, TypeError, ValueError, UnicodeDecodeError) as exc:
        raise RoomStorageError("Stored room data is invalid or incompatible.") from exc


def deserialize_metadata(raw: bytes) -> tuple[int, tuple[CommandReceipt, ...]]:
    """Read and validate v2 metadata; accept earlier v1 active rooms."""

    try:
        if len(raw) > MAX_ROOM_BYTES:
            raise ValueError("Stored room exceeds the size limit.")
        value = json.loads(raw)
        version = value["storage_version"]
        if type(version) is not int or version not in SUPPORTED_STORAGE_VERSIONS:
            raise ValueError("Unsupported room storage version.")
        sequence = value["sequence"] if version >= INTERMEDIATE_STORAGE_VERSION else value.get("sequence", 0)
        if type(sequence) is not int or sequence < 0:
            raise ValueError("Invalid room sequence.")
        receipt_values = value["receipts"] if version >= INTERMEDIATE_STORAGE_VERSION else value.get("receipts", [])
        if not isinstance(receipt_values, list) or len(receipt_values) > MAX_LEGACY_EMBEDDED_RECEIPTS:
            raise ValueError("Invalid stored receipts.")
        receipts = tuple(
            CommandReceipt(
                player_id=item["player_id"],
                request_id=item["request_id"],
                fingerprint=item["fingerprint"],
                sequence=item["sequence"],
                accepted=item["accepted"],
                code=item["code"],
                message=item["message"],
                recorded_at=_date(item["recorded_at"]),
            )
            for item in receipt_values
        )
        if any(item.sequence > sequence for item in receipts):
            raise ValueError("Receipt sequence exceeds room sequence.")
        keys = [(item.player_id, item.request_id) for item in receipts]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate stored request ID.")
        return sequence, receipts
    except (KeyError, TypeError, ValueError, UnicodeDecodeError) as exc:
        raise RoomStorageError("Stored room metadata is invalid.") from exc


def serialize_editor_document(document: EditorDocument) -> bytes:
    """Keep Yjs state separate from the room and bound the entire Redis value."""

    encoded = json.dumps(
        {"storage_version": EDITOR_STORAGE_VERSION, **asdict(document)},
        default=_json_default, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    if len(encoded) > MAX_EDITOR_RECORD_BYTES:
        raise EditorStorageLimitError("Editor document exceeds the storage size limit.")
    return encoded


def deserialize_editor_document(raw: bytes) -> EditorDocument:
    """Read current records and trim oversized legacy history on recovery."""

    try:
        if len(raw) > MAX_LEGACY_EDITOR_RECORD_BYTES:
            raise ValueError("Stored editor document is too large.")
        value = json.loads(raw)
        if type(value) is not dict:
            raise ValueError("Stored editor document must be an object.")
        version = value.get("storage_version", 0)
        if type(version) is not int or version not in {0, EDITOR_STORAGE_VERSION}:
            raise ValueError("Unsupported editor storage version.")
        if version == EDITOR_STORAGE_VERSION and len(raw) > MAX_EDITOR_RECORD_BYTES:
            raise ValueError("Stored editor document exceeds the size limit.")
        history_values = value["history"]
        if type(history_values) is not list:
            raise ValueError("Stored editor history must be a list.")
        if version == EDITOR_STORAGE_VERSION and len(history_values) > MAX_EDITOR_HISTORY_ENTRIES:
            raise ValueError("Stored editor history has too many entries.")
        if version == 0:
            history_values = history_values[-MAX_EDITOR_HISTORY_ENTRIES:]
        history = [EditorRevision(
            revision_id=item["revision_id"], source=item["source"],
            author_player_id=item["author_player_id"],
            recorded_at=_date(item["recorded_at"]),
            restored_from_revision_id=item.get("restored_from_revision_id"),
        ) for item in history_values]
        if version == 0:
            while sum(len(item.source.encode("utf-8")) for item in history) > MAX_EDITOR_HISTORY_BYTES:
                history.pop(0)
        document = EditorDocument(
            revision_id=value["revision_id"], source=value["source"],
            y_state=value["y_state"], history=tuple(history),
        )
        return document
    except (KeyError, TypeError, ValueError, AttributeError, UnicodeDecodeError) as exc:
        raise RoomStorageError("Stored editor document is invalid or incompatible.") from exc
