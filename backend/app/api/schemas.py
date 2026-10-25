"""Public HTTP contracts. Never serialize RoomState directly to a client."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.challenges.loader import load_challenge
from app.game.models import (
    ConnectionStatus, GamePhase, ObjectiveStatus, PlayerRole, RoomState,
)
from app.rooms.identity import normalize_display_name


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateRoomRequest(ApiModel):
    display_name: str = Field(max_length=96)
    capacity: Literal[4, 5] = 5

    @field_validator("display_name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return normalize_display_name(value)


class JoinRoomRequest(ApiModel):
    room_code: str = Field(min_length=1, max_length=32)
    display_name: str = Field(max_length=96)

    @field_validator("display_name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return normalize_display_name(value)


class PublicPlayer(ApiModel):
    player_id: str
    display_name: str
    connection: ConnectionStatus
    is_ready: bool
    is_alive: bool
    is_host: bool


class OwnObjective(ApiModel):
    objective_id: str
    status: ObjectiveStatus


class PublicTestOutcome(ApiModel):
    test_id: str
    name: str
    passed: bool
    required_for_civilian_win: bool
    message: str | None


class OfficialResultSummary(ApiModel):
    run_id: str
    source_revision_id: str
    status: Literal["completed"] = "completed"
    all_required_tests_passed: bool
    tests: tuple[PublicTestOutcome, ...]


class RoomSnapshot(ApiModel):
    room_code: str
    phase: GamePhase
    capacity: int
    expires_at: datetime
    phase_deadline_at: datetime | None
    self_player_id: str
    own_category_vote_id: str | None
    own_role: PlayerRole | None
    own_objectives: tuple[OwnObjective, ...]
    selected_category_id: str | None
    round_number: int | None
    challenge_id: str | None
    challenge_version: str | None
    current_source_revision_id: str | None
    official_result: OfficialResultSummary | None = None
    players: tuple[PublicPlayer, ...]


class RoomResponse(ApiModel):
    room: RoomSnapshot


class ApiError(ApiModel):
    code: str
    message: str


class ErrorResponse(ApiModel):
    error: ApiError


def build_room_response(room: RoomState, player_id: str) -> RoomResponse:
    """Project trusted room state into one guest's authorized HTTP view."""

    player = next(item for item in room.players if item.player_id == player_id)
    match = room.match
    current_round = match.current_round if match is not None else None
    official_summary = None
    if current_round is not None and current_round.official_test_result is not None:
        official = current_round.official_test_result
        loaded = load_challenge(current_round.challenge_id, current_round.challenge_version)
        if loaded.content_digest != current_round.challenge_content_digest:
            raise ValueError("Pinned challenge content changed while projecting its result.")
        passed = set(official.passed_test_ids)
        official_summary = OfficialResultSummary(
            run_id=official.run_id,
            source_revision_id=official.source_revision_id,
            all_required_tests_passed=official.all_required_tests_passed,
            tests=tuple(PublicTestOutcome(
                test_id=test.id, name=test.name, passed=test.id in passed,
                required_for_civilian_win=test.required_for_civilian_win,
                message=None if test.id in passed else test.safe_failure_message,
            ) for test in loaded.challenge.tests if test.visibility == "public"),
        )
    own_objectives = (
        tuple(
            OwnObjective(objective_id=item.objective_id, status=item.status)
            for item in current_round.sabotage_objectives
        )
        if player.role is PlayerRole.IMPOSTOR and current_round is not None
        else ()
    )
    public_players = tuple(
        PublicPlayer(
            player_id=item.player_id,
            display_name=item.display_name,
            connection=item.connection,
            is_ready=item.is_ready,
            is_alive=item.is_alive,
            is_host=item.player_id == room.host_player_id,
        )
        for item in room.players
        if item.connection is not ConnectionStatus.DEPARTED
    )
    return RoomResponse(
        room=RoomSnapshot(
            room_code=room.room_code,
            phase=room.phase,
            capacity=room.capacity,
            expires_at=room.expires_at,
            phase_deadline_at=room.phase_deadline.due_at if room.phase_deadline else None,
            self_player_id=player_id,
            own_category_vote_id=next(
                (vote.target_id for vote in match.category_votes if vote.voter_id == player_id),
                None,
            ) if match else None,
            own_role=player.role,
            own_objectives=own_objectives,
            selected_category_id=match.selected_category_id if match else None,
            round_number=match.round_number if match else None,
            challenge_id=current_round.challenge_id if current_round else None,
            challenge_version=current_round.challenge_version if current_round else None,
            current_source_revision_id=current_round.current_source_revision_id if current_round else None,
            official_result=official_summary,
            players=public_players,
        )
    )
