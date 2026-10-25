"""Typed domain state for CodeMafia rooms and matches.

These frozen dataclasses describe authoritative in-memory state. They are not
HTTP/WebSocket response models: a future transport layer must create explicit
player-authorized snapshots and must never serialize private state wholesale.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import re


class GamePhase(str, Enum):
    """The explicit lifecycle phases a room or match can occupy."""

    LOBBY = "lobby"
    CATEGORY_VOTE = "category_vote"
    ROLE_REVEAL = "role_reveal"
    CODING_ROUND = "coding_round"
    MEETING_DISCUSSION = "meeting_discussion"
    PLAYER_VOTE = "player_vote"
    ROUND_RESULT = "round_result"
    GAME_OVER = "game_over"


class PlayerRole(str, Enum):
    """A player's secret match role; keep it out of public room payloads."""

    CIVILIAN = "civilian"
    IMPOSTOR = "impostor"


class ConnectionStatus(str, Enum):
    """Connection lifecycle, including the reconnect-grace interval."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    DEPARTED = "departed"


class VoteKind(str, Enum):
    """The ballot context determines how a vote's target is interpreted."""

    CATEGORY = "category"
    PLAYER = "player"


class DeadlineKind(str, Enum):
    """Kinds of server-owned deadlines the rules engine may evaluate."""

    ROOM_EXPIRY = "room_expiry"
    CATEGORY_VOTE = "category_vote"
    ROLE_REVEAL = "role_reveal"
    CODING_ROUND = "coding_round"
    MEETING_COOLDOWN = "meeting_cooldown"
    MEETING_DISCUSSION = "meeting_discussion"
    PLAYER_VOTE = "player_vote"
    RECONNECT_GRACE = "reconnect_grace"


class ObjectiveStatus(str, Enum):
    """Server-owned progress for one assigned sabotage objective."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class OfficialRunStatus(str, Enum):
    """Player-safe lifecycle of one official test job."""

    QUEUED = "queued"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    STALE = "stale"


class MatchWinner(str, Enum):
    """The team that won a completed match."""

    CIVILIANS = "civilians"
    IMPOSTOR = "impostor"


class MatchEndReason(str, Enum):
    """The rule that committed the final match result."""

    IMPOSTOR_EJECTED = "impostor_ejected"
    IMPOSTOR_DEPARTED = "impostor_departed"
    REQUIRED_TESTS_PASSED = "required_tests_passed"
    SABOTAGE_OBJECTIVES_COMPLETED = "sabotage_objectives_completed"
    FINAL_DEADLINE_SURVIVED = "final_deadline_survived"


class RoundEndReason(str, Enum):
    """Why the coding portion of a round stopped without ending the match."""

    DEADLINE_EXPIRED = "deadline_expired"


MAX_OFFICIAL_TEST_HISTORY = 32
MAX_TEST_PASS_EVIDENCE = 256
MAX_ROUND_HISTORY = 3


def _require_non_blank(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _require_utc_datetime(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware and use UTC")


@dataclass(frozen=True, slots=True)
class PlayerState:
    """One room member, including trusted and player-private match data."""

    player_id: str
    display_name: str
    joined_at: datetime
    connection: ConnectionStatus = ConnectionStatus.CONNECTED
    is_ready: bool = False
    is_alive: bool = True
    role: PlayerRole | None = None
    emergency_meetings_used: int = 0
    reconnect_deadline: GameDeadline | None = None

    def __post_init__(self) -> None:
        _require_non_blank(self.player_id, "player_id")
        _require_non_blank(self.display_name, "display_name")
        _require_utc_datetime(self.joined_at, "joined_at")
        if not isinstance(self.connection, ConnectionStatus):
            raise ValueError("connection must be a ConnectionStatus")
        if self.role is not None and not isinstance(self.role, PlayerRole):
            raise ValueError("role must be a PlayerRole or None")
        if not isinstance(self.is_ready, bool) or not isinstance(self.is_alive, bool):
            raise ValueError("is_ready and is_alive must be booleans")
        if self.emergency_meetings_used not in (0, 1):
            raise ValueError("emergency_meetings_used must be 0 or 1 per match")
        if self.connection is ConnectionStatus.DISCONNECTED:
            if self.reconnect_deadline is None or self.reconnect_deadline.kind is not DeadlineKind.RECONNECT_GRACE:
                raise ValueError("disconnected players require a reconnect-grace deadline")
        elif self.reconnect_deadline is not None:
            raise ValueError("only disconnected players may have a reconnect-grace deadline")


@dataclass(frozen=True, slots=True)
class Vote:
    """One accepted ballot; a missing target means skip for player votes."""

    kind: VoteKind
    voter_id: str
    target_id: str | None
    request_id: str
    cast_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.kind, VoteKind):
            raise ValueError("kind must be a VoteKind")
        _require_non_blank(self.voter_id, "voter_id")
        _require_non_blank(self.request_id, "request_id")
        _require_utc_datetime(self.cast_at, "cast_at")
        if self.target_id is not None:
            _require_non_blank(self.target_id, "target_id")
        if self.kind is VoteKind.CATEGORY and self.target_id is None:
            raise ValueError("category votes must select a category")


@dataclass(frozen=True, slots=True)
class SabotageObjectiveProgress:
    """Private progress and evidence for an assigned impostor objective."""

    objective_id: str
    status: ObjectiveStatus = ObjectiveStatus.NOT_STARTED
    verified_revision_id: str | None = None
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_non_blank(self.objective_id, "objective_id")
        if not isinstance(self.status, ObjectiveStatus):
            raise ValueError("status must be an ObjectiveStatus")
        if self.status is ObjectiveStatus.COMPLETED:
            if self.verified_revision_id is None or self.completed_at is None:
                raise ValueError(
                    "completed objectives require a verified revision and completion time"
                )
            _require_non_blank(self.verified_revision_id, "verified_revision_id")
            _require_utc_datetime(self.completed_at, "completed_at")
        elif self.verified_revision_id is not None or self.completed_at is not None:
            raise ValueError(
                "only completed objectives may contain completion evidence"
            )


@dataclass(frozen=True, slots=True)
class GameDeadline:
    """An absolute server-time deadline, never a client-decremented timer."""

    deadline_id: str
    kind: DeadlineKind
    due_at: datetime

    def __post_init__(self) -> None:
        _require_non_blank(self.deadline_id, "deadline_id")
        if not isinstance(self.kind, DeadlineKind):
            raise ValueError("kind must be a DeadlineKind")
        _require_utc_datetime(self.due_at, "due_at")


@dataclass(frozen=True, slots=True)
class OfficialTestResult:
    """Trusted runner result bound to the exact source revision it tested."""

    run_id: str
    source_revision_id: str
    completed_at: datetime
    passed_test_ids: tuple[str, ...] = ()
    failed_test_ids: tuple[str, ...] = ()
    all_required_tests_passed: bool = False

    def __post_init__(self) -> None:
        _require_non_blank(self.run_id, "run_id")
        _require_non_blank(self.source_revision_id, "source_revision_id")
        _require_utc_datetime(self.completed_at, "completed_at")
        for test_id in (*self.passed_test_ids, *self.failed_test_ids):
            _require_non_blank(test_id, "test IDs")
        if len(set(self.passed_test_ids)) != len(self.passed_test_ids):
            raise ValueError("passed_test_ids cannot contain duplicates")
        if len(set(self.failed_test_ids)) != len(self.failed_test_ids):
            raise ValueError("failed_test_ids cannot contain duplicates")
        if set(self.passed_test_ids).intersection(self.failed_test_ids):
            raise ValueError("a test cannot be both passed and failed in one run")
        if len(self.passed_test_ids) + len(self.failed_test_ids) > MAX_TEST_PASS_EVIDENCE:
            raise ValueError("one official result contains too many test IDs")


@dataclass(frozen=True, slots=True)
class TestPassEvidence:
    """A durable proof that one named test passed on a particular revision."""

    test_id: str
    source_revision_id: str
    run_id: str
    completed_at: datetime

    def __post_init__(self) -> None:
        _require_non_blank(self.test_id, "test_id")
        _require_non_blank(self.source_revision_id, "source_revision_id")
        _require_non_blank(self.run_id, "run_id")
        _require_utc_datetime(self.completed_at, "completed_at")


@dataclass(frozen=True, slots=True)
class OfficialRunProgress:
    """Bounded, safe-to-project status metadata for an official run."""

    run_id: str
    source_revision_id: str
    requested_by_player_id: str
    requested_at: datetime
    updated_at: datetime
    status: OfficialRunStatus

    def __post_init__(self) -> None:
        _require_non_blank(self.run_id, "run_id")
        _require_non_blank(self.source_revision_id, "source_revision_id")
        _require_non_blank(self.requested_by_player_id, "requested_by_player_id")
        _require_utc_datetime(self.requested_at, "requested_at")
        _require_utc_datetime(self.updated_at, "updated_at")
        if self.updated_at < self.requested_at:
            raise ValueError("run status cannot precede its request")
        if not isinstance(self.status, OfficialRunStatus):
            raise ValueError("status must be an OfficialRunStatus")


@dataclass(frozen=True, slots=True)
class RoundState:
    """The selected, version-pinned challenge and state for one round."""

    number: int
    category_id: str
    challenge_id: str
    challenge_version: str
    challenge_content_digest: str
    started_at: datetime
    deadline: GameDeadline
    current_source_revision_id: str
    official_test_result: OfficialTestResult | None = None
    official_test_history: tuple[OfficialTestResult, ...] = ()
    official_run_progress: tuple[OfficialRunProgress, ...] = ()
    test_pass_evidence: tuple[TestPassEvidence, ...] = ()
    sabotage_objectives: tuple[SabotageObjectiveProgress, ...] = ()
    ended_at: datetime | None = None
    end_reason: RoundEndReason | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.number <= 4:
            raise ValueError("round number must be between 1 and 4")
        _require_non_blank(self.category_id, "category_id")
        _require_non_blank(self.challenge_id, "challenge_id")
        _require_non_blank(self.challenge_version, "challenge_version")
        _require_non_blank(self.challenge_content_digest, "challenge_content_digest")
        _require_non_blank(self.current_source_revision_id, "current_source_revision_id")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", self.current_source_revision_id) is None:
            raise ValueError("current_source_revision_id has an invalid format")
        _require_utc_datetime(self.started_at, "started_at")
        if self.deadline.kind is not DeadlineKind.CODING_ROUND:
            raise ValueError("round deadline must have kind CODING_ROUND")
        if self.deadline.due_at <= self.started_at:
            raise ValueError("round deadline must be after the round start")
        if len(self.official_test_history) > MAX_OFFICIAL_TEST_HISTORY:
            raise ValueError("official test history exceeds its bound")
        if len(self.official_run_progress) > MAX_OFFICIAL_TEST_HISTORY:
            raise ValueError("official run progress exceeds its bound")
        if len(self.test_pass_evidence) > MAX_TEST_PASS_EVIDENCE:
            raise ValueError("test pass evidence exceeds its bound")
        if any(not isinstance(item, OfficialTestResult) for item in self.official_test_history):
            raise ValueError("official_test_history contains an invalid result")
        if any(not isinstance(item, TestPassEvidence) for item in self.test_pass_evidence):
            raise ValueError("test_pass_evidence contains invalid evidence")
        if any(not isinstance(item, OfficialRunProgress) for item in self.official_run_progress):
            raise ValueError("official_run_progress contains invalid entries")
        if len({item.run_id for item in self.official_run_progress}) != len(self.official_run_progress):
            raise ValueError("official run progress cannot repeat a run ID")
        if self.official_test_history and len({item.run_id for item in self.official_test_history}) != len(self.official_test_history):
            raise ValueError("official test history cannot repeat a runner ID")
        if self.official_test_result is not None and (
            self.official_test_result.source_revision_id != self.current_source_revision_id
        ):
            raise ValueError("current official result must match the current source revision")
        if self.ended_at is None:
            if self.end_reason is not None:
                raise ValueError("an end reason requires ended_at")
        else:
            _require_utc_datetime(self.ended_at, "ended_at")
            if self.end_reason is None:
                raise ValueError("ended_at requires a round end reason")
            if self.ended_at < self.started_at:
                raise ValueError("round cannot end before it starts")
        if len({item.test_id for item in self.test_pass_evidence}) != len(self.test_pass_evidence):
            raise ValueError("test pass evidence must contain one entry per test ID")
        objective_ids = [item.objective_id for item in self.sabotage_objectives]
        if len(objective_ids) != len(set(objective_ids)):
            raise ValueError("sabotage objective IDs must be unique within a round")


@dataclass(frozen=True, slots=True)
class MatchResult:
    """Committed match outcome; round outcomes are represented separately."""

    winner: MatchWinner
    reason: MatchEndReason
    round_number: int
    ended_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.winner, MatchWinner):
            raise ValueError("winner must be a MatchWinner")
        if not isinstance(self.reason, MatchEndReason):
            raise ValueError("reason must be a MatchEndReason")
        if not 0 <= self.round_number <= 4:
            raise ValueError("match result round_number must be between 0 and 4")
        if self.round_number == 0 and self.reason is not MatchEndReason.IMPOSTOR_DEPARTED:
            raise ValueError("only an impostor departure may end a match before round 1")
        _require_utc_datetime(self.ended_at, "ended_at")
        if (
            self.reason is MatchEndReason.FINAL_DEADLINE_SURVIVED
            and self.round_number != 4
        ):
            raise ValueError("surviving the final deadline can only end round 4")
        expected_winner = {
            MatchEndReason.IMPOSTOR_EJECTED: MatchWinner.CIVILIANS,
            MatchEndReason.IMPOSTOR_DEPARTED: MatchWinner.CIVILIANS,
            MatchEndReason.REQUIRED_TESTS_PASSED: MatchWinner.CIVILIANS,
            MatchEndReason.SABOTAGE_OBJECTIVES_COMPLETED: MatchWinner.IMPOSTOR,
            MatchEndReason.FINAL_DEADLINE_SURVIVED: MatchWinner.IMPOSTOR,
        }[self.reason]
        if self.winner is not expected_winner:
            raise ValueError("winner does not match the selected match-end reason")


@dataclass(frozen=True, slots=True)
class VoteResolution:
    """Public aggregate retained so reconnecting players can see the last vote."""

    vote_counts: tuple[tuple[str, int], ...]
    skip_count: int
    ejected_player_id: str | None
    was_tie: bool
    resolved_at: datetime

    def __post_init__(self) -> None:
        if self.skip_count < 0 or any(count < 0 for _, count in self.vote_counts):
            raise ValueError("vote counts must be non-negative")
        if len({player_id for player_id, _ in self.vote_counts}) != len(self.vote_counts):
            raise ValueError("vote targets must be unique")
        if self.ejected_player_id is not None:
            _require_non_blank(self.ejected_player_id, "ejected_player_id")
        _require_utc_datetime(self.resolved_at, "resolved_at")


@dataclass(frozen=True, slots=True)
class MatchState:
    """Match-wide state that persists across its rounds."""

    match_id: str | None = None
    round_number: int = 0
    selected_category_id: str | None = None
    category_votes: tuple[Vote, ...] = ()
    player_votes: tuple[Vote, ...] = ()
    last_vote_result: VoteResolution | None = None
    round_history: tuple[RoundState, ...] = ()
    current_round: RoundState | None = None
    result: MatchResult | None = None
    meeting_started_at: datetime | None = None
    paused_round_deadline: GameDeadline | None = None
    meeting_cooldown_until: datetime | None = None
    rematch_requests: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.match_id is not None:
            _require_non_blank(self.match_id, "match_id")
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", self.match_id) is None:
                raise ValueError("match_id has an invalid format")
        if not 0 <= self.round_number <= 4:
            raise ValueError("round_number must be between 0 and 4")
        if self.current_round is not None and self.current_round.number != self.round_number:
            raise ValueError("current_round.number must match round_number")
        if self.current_round is None and self.round_number > 0:
            raise ValueError("a match past category selection must have a current round")
        if len(self.round_history) > MAX_ROUND_HISTORY:
            raise ValueError("round history exceeds the match limit")
        if any(not isinstance(item, RoundState) for item in self.round_history):
            raise ValueError("round history contains an invalid round")
        history_numbers = tuple(item.number for item in self.round_history)
        if history_numbers != tuple(sorted(set(history_numbers))):
            raise ValueError("round history must have unique increasing round numbers")
        if self.current_round is not None and any(
            item.number >= self.current_round.number for item in self.round_history
        ):
            raise ValueError("round history must precede the current round")
        if self.result is not None and self.result.round_number != self.round_number:
            raise ValueError("match result round must match the current round")
        if any(vote.kind is not VoteKind.CATEGORY for vote in self.category_votes):
            raise ValueError("category_votes may contain only category ballots")
        if any(vote.kind is not VoteKind.PLAYER for vote in self.player_votes):
            raise ValueError("player_votes may contain only player ballots")
        if self.last_vote_result is not None and not isinstance(self.last_vote_result, VoteResolution):
            raise ValueError("last_vote_result must be a VoteResolution")
        if (self.meeting_started_at is None) != (self.paused_round_deadline is None):
            raise ValueError(
                "meeting_started_at and paused_round_deadline must be set together"
            )
        if self.meeting_started_at is not None:
            _require_utc_datetime(self.meeting_started_at, "meeting_started_at")
        if self.meeting_cooldown_until is not None:
            _require_utc_datetime(self.meeting_cooldown_until, "meeting_cooldown_until")
        if len(self.rematch_requests) != len(set(self.rematch_requests)):
            raise ValueError("rematch_requests cannot contain duplicate player IDs")
        for player_id in self.rematch_requests:
            _require_non_blank(player_id, "rematch requester ID")


@dataclass(frozen=True, slots=True)
class RoomState:
    """Authoritative room aggregate; includes private data and is not a DTO."""

    room_code: str
    host_player_id: str
    players: tuple[PlayerState, ...]
    created_at: datetime
    expires_at: datetime
    phase: GamePhase = GamePhase.LOBBY
    capacity: int = 5
    phase_deadline: GameDeadline | None = None
    match: MatchState | None = None
    is_closed: bool = False

    def __post_init__(self) -> None:
        _require_non_blank(self.room_code, "room_code")
        _require_non_blank(self.host_player_id, "host_player_id")
        _require_utc_datetime(self.created_at, "created_at")
        _require_utc_datetime(self.expires_at, "expires_at")
        if not isinstance(self.phase, GamePhase):
            raise ValueError("phase must be a GamePhase")
        if self.expires_at <= self.created_at:
            raise ValueError("room expiry must be after room creation")
        if self.capacity not in (4, 5):
            raise ValueError("room capacity must be 4 or 5")
        player_ids = [player.player_id for player in self.players]
        if len(player_ids) != len(set(player_ids)):
            raise ValueError("player IDs must be unique within a room")
        active_count = sum(
            player.connection is not ConnectionStatus.DEPARTED for player in self.players
        )
        if active_count > self.capacity:
            raise ValueError("room cannot contain more active players than its capacity")
        if self.host_player_id not in player_ids:
            raise ValueError("host_player_id must identify a player in the room")
        if self.phase is GamePhase.LOBBY and self.match is not None:
            raise ValueError("a lobby room cannot already contain an active match")
        if self.phase is not GamePhase.LOBBY and self.match is None:
            raise ValueError("non-lobby phases require match state")
        if self.phase is GamePhase.GAME_OVER:
            if self.match is None or self.match.result is None:
                raise ValueError("GAME_OVER requires a committed match result")
        elif self.match is not None and self.match.result is not None:
            raise ValueError("a committed match result requires the GAME_OVER phase")
        if not isinstance(self.is_closed, bool):
            raise ValueError("is_closed must be a boolean")
