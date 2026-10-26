"""Public HTTP contracts. Never serialize RoomState directly to a client."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.challenges.loader import load_challenge
from app.game.models import (
    ConnectionStatus, GamePhase, ObjectiveStatus, OfficialRunStatus, PlayerRole,
    RoomState, RoundEndReason, MAX_SABOTAGE_CREDITS,
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
    private_description: str


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


class OfficialRunSummary(ApiModel):
    run_id: str
    source_revision_id: str
    status: OfficialRunStatus
    requested_at: datetime


class MatchResultSummary(ApiModel):
    winner: Literal["civilians", "impostor"]
    reason: str
    round_number: int


class VoteResultSummary(ApiModel):
    vote_counts: dict[str, int]
    skip_count: int
    ejected_player_id: str | None
    was_tie: bool
    resolved_at: datetime


class ChatMessageSummary(ApiModel):
    message_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    player_id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=96)
    message: str = Field(min_length=1, max_length=500)
    sent_at: datetime


class RoomSnapshot(ApiModel):
    room_code: str
    phase: GamePhase
    capacity: int
    expires_at: datetime
    phase_deadline_at: datetime | None
    self_player_id: str
    own_category_vote_id: str | None
    has_cast_player_vote: bool
    own_player_vote_target_id: str | None
    own_meetings_used: int
    meeting_cooldown_until: datetime | None
    chat_messages: tuple[ChatMessageSummary, ...] = Field(max_length=100)
    own_role: PlayerRole | None
    own_objectives: tuple[OwnObjective, ...]
    own_sabotage_credits_remaining: int | None = None
    own_sabotage_cooldown_until: datetime | None = None
    selected_category_id: str | None
    round_number: int | None
    round_ended_at: datetime | None
    round_end_reason: RoundEndReason | None
    challenge_id: str | None
    challenge_version: str | None
    current_source_revision_id: str | None
    official_result: OfficialResultSummary | None = None
    official_runs: tuple[OfficialRunSummary, ...] = ()
    match_result: MatchResultSummary | None = None
    last_vote_result: VoteResultSummary | None = None
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
    own_objectives = ()
    if player.role is PlayerRole.IMPOSTOR and current_round is not None:
        loaded_objectives = load_challenge(current_round.challenge_id, current_round.challenge_version)
        if loaded_objectives.content_digest != current_round.challenge_content_digest:
            raise ValueError("Pinned challenge content changed while projecting objectives.")
        descriptions = {
            objective.id: objective.private_description
            for objective in loaded_objectives.challenge.sabotage_objectives
        }
        own_objectives = tuple(
            OwnObjective(
                objective_id=item.objective_id,
                status=item.status,
                private_description=descriptions[item.objective_id],
            )
            for item in current_round.sabotage_objectives
        )
    official_runs = (
        tuple(
            OfficialRunSummary(
                run_id=item.run_id,
                source_revision_id=item.source_revision_id,
                status=item.status,
                requested_at=item.requested_at,
            )
            for item in current_round.official_run_progress
        )
        if current_round is not None
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
            has_cast_player_vote=any(
                vote.voter_id == player_id for vote in match.player_votes
            ) if match else False,
            own_player_vote_target_id=next(
                (vote.target_id for vote in match.player_votes if vote.voter_id == player_id),
                None,
            ) if match else None,
            own_meetings_used=player.emergency_meetings_used,
            meeting_cooldown_until=match.meeting_cooldown_until if match else None,
            chat_messages=tuple(ChatMessageSummary(
                message_id=item.message_id,
                player_id=item.player_id,
                display_name=item.display_name,
                message=item.message,
                sent_at=item.sent_at,
            ) for item in room.chat_messages),
            own_role=player.role,
            own_objectives=own_objectives,
            own_sabotage_credits_remaining=(MAX_SABOTAGE_CREDITS - match.sabotage_credits_used
                                           if match and player.role is PlayerRole.IMPOSTOR else None),
            own_sabotage_cooldown_until=(match.sabotage_cooldown_until
                                        if match and player.role is PlayerRole.IMPOSTOR else None),
            selected_category_id=match.selected_category_id if match else None,
            round_number=match.round_number if match else None,
            round_ended_at=current_round.ended_at if current_round else None,
            round_end_reason=current_round.end_reason if current_round else None,
            challenge_id=current_round.challenge_id if current_round else None,
            challenge_version=current_round.challenge_version if current_round else None,
            current_source_revision_id=current_round.current_source_revision_id if current_round else None,
            official_result=official_summary,
            official_runs=official_runs,
            match_result=(
                MatchResultSummary(
                    winner=match.result.winner.value,
                    reason=match.result.reason.value,
                    round_number=match.result.round_number,
                ) if match and match.result else None
            ),
            last_vote_result=(
                VoteResultSummary(
                    vote_counts=dict(match.last_vote_result.vote_counts),
                    skip_count=match.last_vote_result.skip_count,
                    ejected_player_id=match.last_vote_result.ejected_player_id,
                    was_tie=match.last_vote_result.was_tie,
                    resolved_at=match.last_vote_result.resolved_at,
                ) if match and match.last_vote_result else None
            ),
            players=public_players,
        )
    )
