"""Pure state transitions for the CodeMafia game domain.

Functions in this module accept a snapshot, an action or server-time event, and
explicit choices/deadlines. They return a new snapshot plus domain events, or
the original snapshot with a typed rejection. They do not perform I/O, load
challenge files, run player code, or generate randomness themselves.

Ordering rule: a player action is too late when ``now >= deadline.due_at``.
The deadline event therefore wins a race at the exact deadline. The caller must
serialize calls for a room and supply choices made by its injected selector.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta
from typing import TypeAlias

from .commands import (
    CallEmergencyMeeting,
    CastCategoryVote,
    CastPlayerVote,
    EndRoom,
    GameCommandType,
    LeaveRoom,
    RequestOfficialTestRun,
    RequestRematch,
    SendChatMessage,
    SetReady,
    StartMatch,
)
from .events import (
    CategorySelected,
    CategoryVoteRecorded,
    ChatMessagePosted,
    CodingRoundStarted,
    GameEvent,
    HostTransferred,
    MatchEnded,
    MatchStarted,
    MeetingStarted,
    OfficialTestResultAccepted,
    OfficialTestRunRequested,
    PlayerBallotStored,
    PlayerDeparted,
    PlayerDisconnected,
    PlayerEliminated,
    PlayerReconnected,
    PlayerReadinessChanged,
    PlayerRoleAssigned,
    PlayerVoteResolved,
    PlayerVotingStarted,
    RematchRequested,
    RematchStarted,
    RoomClosed,
    RoundEnded,
    SabotageObjectiveVerified,
    SourceRevisionChanged,
)
from .deadlines import (
    DeadlineStatus,
    action_is_before_deadline,
    evaluate_deadline,
    require_utc_time,
)
from .models import (
    ConnectionStatus,
    DeadlineKind,
    GameDeadline,
    GamePhase,
    MatchEndReason,
    MatchResult,
    MatchState,
    MatchWinner,
    OfficialTestResult,
    ObjectiveStatus,
    PlayerRole,
    PlayerState,
    RoomState,
    RoundState,
    Vote,
    VoteKind,
)
from .outcomes import (
    RejectionCode,
    TransitionAccepted,
    TransitionOutcome,
    TransitionRejected,
)


SUPPORTED_CATEGORY_IDS: tuple[str, ...] = (
    "data-structures-algorithms",
    "object-oriented",
    "security",
    "front-end",
    "back-end",
)
MAX_ROUNDS = 4
MIN_PLAYERS = 4

Command: TypeAlias = GameCommandType


def _validate_now(now: datetime) -> None:
    require_utc_time(now)


def _room_unavailable(state: RoomState, now: datetime) -> bool:
    return state.is_closed or now >= state.expires_at


def _reject(
    state: RoomState,
    code: RejectionCode,
    message: str,
    request_id: str | None = None,
) -> TransitionRejected:
    return TransitionRejected(
        state=state,
        code=code,
        message=message,
        request_id=request_id,
    )


def _accepted(
    state: RoomState,
    *events: GameEvent,
) -> TransitionAccepted:
    return TransitionAccepted(state=state, events=tuple(events))


def _player_index(state: RoomState, player_id: str) -> int | None:
    for index, player in enumerate(state.players):
        if player.player_id == player_id:
            return index
    return None


def _eligible_connected_players(state: RoomState) -> tuple[PlayerState, ...]:
    return tuple(
        player
        for player in state.players
        if player.connection is ConnectionStatus.CONNECTED and player.is_alive
    )


def _find_player(
    state: RoomState,
    player_id: str,
    *,
    require_connected: bool = True,
    require_alive: bool = False,
) -> PlayerState | None:
    index = _player_index(state, player_id)
    if index is None:
        return None
    player = state.players[index]
    if player.connection is ConnectionStatus.DEPARTED:
        return None
    if require_connected and player.connection is not ConnectionStatus.CONNECTED:
        return None
    if require_alive and not player.is_alive:
        return None
    return player


def _deadline_is_open(state: RoomState, now: datetime) -> bool:
    return action_is_before_deadline(state.phase_deadline, now)


def _validate_supplied_deadline(
    deadline: GameDeadline | None,
    expected_kind: DeadlineKind,
    now: datetime,
) -> RejectionCode | None:
    evaluation = evaluate_deadline(deadline, now, expected_kind=expected_kind)
    if evaluation.status is DeadlineStatus.NO_DEADLINE:
        return RejectionCode.MISSING_DEADLINE
    if evaluation.status is not DeadlineStatus.OPEN:
        return RejectionCode.INVALID_DEADLINE
    return None


def apply_command(
    state: RoomState,
    command: Command,
    now: datetime,
    *,
    next_deadline: GameDeadline | None = None,
    meeting_cooldown_until: datetime | None = None,
) -> TransitionOutcome:
    """Validate and apply one player command without mutating ``state``.

    ``next_deadline`` is supplied by the trusted room coordinator for actions
    that begin a timed phase. Durations are intentionally not invented here.
    The acting player ID must already have been bound to the authenticated
    connection by the caller.
    """

    _validate_now(now)
    request_id = command.request_id

    if _room_unavailable(state, now):
        return _reject(state, RejectionCode.ROOM_CLOSED, "This room is closed.", request_id)

    if isinstance(command, SetReady):
        return _set_ready(state, command, now)
    if isinstance(command, StartMatch):
        return _start_match(state, command, now, next_deadline)
    if isinstance(command, CastCategoryVote):
        return _cast_category_vote(state, command, now)
    if isinstance(command, CallEmergencyMeeting):
        return _call_meeting(
            state,
            command,
            now,
            next_deadline,
            meeting_cooldown_until,
        )
    if isinstance(command, CastPlayerVote):
        return _cast_player_vote(state, command, now)
    if isinstance(command, RequestOfficialTestRun):
        return _request_test_run(state, command, now)
    if isinstance(command, SendChatMessage):
        return _send_chat(state, command, now)
    if isinstance(command, LeaveRoom):
        return _leave_room(state, command, now)
    if isinstance(command, EndRoom):
        return _end_room(state, command, now)
    if isinstance(command, RequestRematch):
        return _request_rematch(state, command, now)

    return _reject(
        state,
        RejectionCode.ACTION_NOT_SUPPORTED,
        "This action is not supported by the game engine.",
        request_id,
    )


def _set_ready(
    state: RoomState,
    command: SetReady,
    now: datetime,
) -> TransitionOutcome:
    if state.phase is not GamePhase.LOBBY:
        return _reject(state, RejectionCode.WRONG_PHASE, "Ready state can only change in the lobby.", command.request_id)
    if not _deadline_is_open(state, now):
        return _reject(state, RejectionCode.DEADLINE_PASSED, "The room deadline has passed.", command.request_id)
    player = _find_player(state, command.player_id, require_alive=True)
    if player is None:
        return _reject(state, RejectionCode.PLAYER_NOT_FOUND, "Player is not an active room member.", command.request_id)
    if player.is_ready is command.ready:
        return _accepted(state)

    index = _player_index(state, command.player_id)
    assert index is not None
    players = list(state.players)
    players[index] = replace(player, is_ready=command.ready)
    updated = replace(state, players=tuple(players))
    return _accepted(
        updated,
        PlayerReadinessChanged(
            occurred_at=now,
            request_id=command.request_id,
            player_id=command.player_id,
            is_ready=command.ready,
        ),
    )


def _start_match(
    state: RoomState,
    command: StartMatch,
    now: datetime,
    next_deadline: GameDeadline | None,
) -> TransitionOutcome:
    if state.phase is not GamePhase.LOBBY:
        return _reject(state, RejectionCode.WRONG_PHASE, "A match can only start from the lobby.", command.request_id)
    if command.player_id != state.host_player_id:
        return _reject(state, RejectionCode.NOT_HOST, "Only the host can start the match.", command.request_id)
    host = _find_player(state, command.player_id, require_alive=True)
    if host is None:
        return _reject(state, RejectionCode.PLAYER_NOT_CONNECTED, "The host must be connected to start.", command.request_id)

    eligible = _eligible_connected_players(state)
    if not MIN_PLAYERS <= len(eligible) <= state.capacity:
        return _reject(state, RejectionCode.INVALID_PLAYER_COUNT, "A match needs four or five connected players.", command.request_id)
    if any(not player.is_ready for player in eligible):
        return _reject(state, RejectionCode.NOT_READY, "Every connected player must be ready.", command.request_id)
    deadline_error = _validate_supplied_deadline(
        next_deadline,
        DeadlineKind.CATEGORY_VOTE,
        now,
    )
    if deadline_error is not None:
        return _reject(state, deadline_error, "A future category-vote deadline is required.", command.request_id)

    updated = replace(
        state,
        phase=GamePhase.CATEGORY_VOTE,
        phase_deadline=next_deadline,
        match=MatchState(),
    )
    return _accepted(
        updated,
        MatchStarted(occurred_at=now, request_id=command.request_id, room_code=state.room_code),
    )


def _cast_category_vote(
    state: RoomState,
    command: CastCategoryVote,
    now: datetime,
) -> TransitionOutcome:
    if state.phase is not GamePhase.CATEGORY_VOTE or state.match is None:
        return _reject(state, RejectionCode.WRONG_PHASE, "Category voting is not open.", command.request_id)
    if not _deadline_is_open(state, now):
        return _reject(state, RejectionCode.DEADLINE_PASSED, "The category-vote deadline has passed.", command.request_id)
    player = _find_player(state, command.player_id, require_alive=True)
    if player is None:
        return _reject(state, RejectionCode.PLAYER_NOT_CONNECTED, "Only a connected living player may vote.", command.request_id)
    if command.category_id not in SUPPORTED_CATEGORY_IDS:
        return _reject(state, RejectionCode.INVALID_CATEGORY, "That category is not supported.", command.request_id)
    if any(vote.voter_id == command.player_id for vote in state.match.category_votes):
        return _reject(state, RejectionCode.ALREADY_VOTED, "You have already cast a category vote.", command.request_id)

    vote = Vote(
        kind=VoteKind.CATEGORY,
        voter_id=command.player_id,
        target_id=command.category_id,
        request_id=command.request_id,
        cast_at=now,
    )
    updated_match = replace(state.match, category_votes=(*state.match.category_votes, vote))
    updated = replace(state, match=updated_match)
    return _accepted(
        updated,
        CategoryVoteRecorded(
            occurred_at=now,
            request_id=command.request_id,
            player_id=command.player_id,
            category_id=command.category_id,
        ),
    )


def resolve_category_vote(
    state: RoomState,
    now: datetime,
    *,
    selected_category_id: str,
    impostor_player_id: str,
    role_reveal_deadline: GameDeadline,
) -> TransitionOutcome:
    """Resolve a complete/expired category ballot using injected selections.

    The caller supplies the category selected by a deterministic chooser and
    the impostor selected by the injected role selector. Both choices are
    validated here, making the transition replayable without hidden randomness.
    """

    _validate_now(now)
    if _room_unavailable(state, now):
        return _reject(state, RejectionCode.ROOM_CLOSED, "This room is closed.")
    if state.phase is not GamePhase.CATEGORY_VOTE or state.match is None:
        return _reject(state, RejectionCode.WRONG_PHASE, "Category voting is not open.")
    if selected_category_id not in SUPPORTED_CATEGORY_IDS:
        return _reject(state, RejectionCode.INVALID_SELECTION, "The selected category is unsupported.")
    deadline_error = _validate_supplied_deadline(
        role_reveal_deadline,
        DeadlineKind.ROLE_REVEAL,
        now,
    )
    if deadline_error is not None:
        return _reject(state, deadline_error, "A future role-reveal deadline is required.")

    eligible = _eligible_connected_players(state)
    votes = state.match.category_votes
    all_voted = bool(eligible) and all(
        any(vote.voter_id == player.player_id for vote in votes)
        for player in eligible
    )
    deadline_passed = not _deadline_is_open(state, now)
    if not all_voted and not deadline_passed:
        return _reject(state, RejectionCode.VOTE_NOT_COMPLETE, "Category voting is still in progress.")

    counts = Counter(vote.target_id for vote in votes if vote.target_id is not None)
    if counts:
        highest = max(counts.values())
        winning_candidates = tuple(sorted(category for category, count in counts.items() if count == highest))
    else:
        winning_candidates = SUPPORTED_CATEGORY_IDS
    if selected_category_id not in winning_candidates:
        return _reject(state, RejectionCode.INVALID_SELECTION, "The selected category did not win the vote.")

    participants = tuple(
        player for player in state.players if player.connection is not ConnectionStatus.DEPARTED
    )
    if not any(player.player_id == impostor_player_id for player in participants):
        return _reject(state, RejectionCode.INVALID_SELECTION, "The impostor selection is not an active match player.")
    if not MIN_PLAYERS <= len(participants) <= state.capacity:
        return _reject(state, RejectionCode.INVALID_PLAYER_COUNT, "The match no longer has enough eligible players.")

    players: list[PlayerState] = []
    events: list[GameEvent] = [
        CategorySelected(
            occurred_at=now,
            request_id=None,
            category_id=selected_category_id,
            vote_counts=tuple(sorted((category, count) for category, count in counts.items())),
            used_fallback=(not counts or len(winning_candidates) > 1),
        )
    ]
    for player in state.players:
        if player.connection is ConnectionStatus.DEPARTED:
            players.append(player)
            continue
        role = PlayerRole.IMPOSTOR if player.player_id == impostor_player_id else PlayerRole.CIVILIAN
        players.append(replace(player, role=role))
        events.append(
            PlayerRoleAssigned(
                occurred_at=now,
                request_id=None,
                recipient_player_id=player.player_id,
                role=role,
            )
        )

    updated_match = replace(state.match, selected_category_id=selected_category_id)
    updated = replace(
        state,
        players=tuple(players),
        phase=GamePhase.ROLE_REVEAL,
        phase_deadline=role_reveal_deadline,
        match=updated_match,
    )
    return _accepted(updated, *events)


def start_coding_round(
    state: RoomState,
    round_state: RoundState,
    now: datetime,
) -> TransitionOutcome:
    """Enter a selected challenge round after role reveal or round results."""

    _validate_now(now)
    if _room_unavailable(state, now):
        return _reject(state, RejectionCode.ROOM_CLOSED, "This room is closed.")
    if state.phase not in {GamePhase.ROLE_REVEAL, GamePhase.ROUND_RESULT} or state.match is None:
        return _reject(state, RejectionCode.WRONG_PHASE, "A coding round cannot start in this phase.")
    if state.phase is GamePhase.ROLE_REVEAL:
        if state.phase_deadline is None or state.phase_deadline.kind is not DeadlineKind.ROLE_REVEAL:
            return _reject(state, RejectionCode.INVALID_DEADLINE, "The role reveal has no valid deadline.")
        if now < state.phase_deadline.due_at:
            return _reject(state, RejectionCode.DEADLINE_NOT_REACHED, "The role reveal is still active.")
    if state.match.selected_category_id is None:
        return _reject(state, RejectionCode.INVALID_SELECTION, "The match has no selected category.")
    expected_round = state.match.round_number + 1
    if expected_round > MAX_ROUNDS or round_state.number != expected_round:
        return _reject(state, RejectionCode.INVALID_SELECTION, "The challenge has the wrong round number.")
    if round_state.category_id != state.match.selected_category_id:
        return _reject(state, RejectionCode.INVALID_SELECTION, "The challenge is outside the selected category.")
    if round_state.started_at > now or round_state.deadline.due_at <= now:
        return _reject(state, RejectionCode.INVALID_DEADLINE, "The round start cannot be in the future and its deadline must remain ahead.")
    if sum(player.role is PlayerRole.IMPOSTOR for player in state.players) != 1:
        return _reject(state, RejectionCode.INVALID_SELECTION, "The match must have exactly one impostor.")

    updated_match = replace(
        state.match,
        round_number=round_state.number,
        current_round=round_state,
        player_votes=(),
    )
    updated = replace(
        state,
        phase=GamePhase.CODING_ROUND,
        phase_deadline=round_state.deadline,
        match=updated_match,
    )
    return _accepted(
        updated,
        CodingRoundStarted(
            occurred_at=now,
            request_id=None,
            round_number=round_state.number,
            category_id=round_state.category_id,
            challenge_id=round_state.challenge_id,
            challenge_version=round_state.challenge_version,
            challenge_content_digest=round_state.challenge_content_digest,
            deadline_at=round_state.deadline.due_at,
        ),
    )


def _call_meeting(
    state: RoomState,
    command: CallEmergencyMeeting,
    now: datetime,
    discussion_deadline: GameDeadline | None,
    meeting_cooldown_until: datetime | None,
) -> TransitionOutcome:
    if state.phase is not GamePhase.CODING_ROUND or state.match is None or state.match.current_round is None:
        return _reject(state, RejectionCode.WRONG_PHASE, "A meeting can only be called during a coding round.", command.request_id)
    if not _deadline_is_open(state, now):
        return _reject(state, RejectionCode.DEADLINE_PASSED, "The coding-round deadline has passed.", command.request_id)
    player = _find_player(state, command.player_id, require_alive=True)
    if player is None:
        return _reject(state, RejectionCode.PLAYER_NOT_CONNECTED, "Only a connected living player may call a meeting.", command.request_id)
    if player.emergency_meetings_used >= 1:
        return _reject(state, RejectionCode.MEETING_ALREADY_USED, "You have already called your meeting this match.", command.request_id)
    if state.match.meeting_cooldown_until is not None and now < state.match.meeting_cooldown_until:
        return _reject(state, RejectionCode.MEETING_COOLDOWN, "The room meeting cooldown is still active.", command.request_id)
    deadline_error = _validate_supplied_deadline(
        discussion_deadline,
        DeadlineKind.MEETING_DISCUSSION,
        now,
    )
    if deadline_error is not None:
        return _reject(state, deadline_error, "A future discussion deadline is required.", command.request_id)
    if meeting_cooldown_until is None or meeting_cooldown_until <= now:
        return _reject(state, RejectionCode.INVALID_DEADLINE, "A future meeting cooldown deadline is required.", command.request_id)

    index = _player_index(state, command.player_id)
    assert index is not None
    players = list(state.players)
    players[index] = replace(player, emergency_meetings_used=1)
    updated_match = replace(
        state.match,
        meeting_started_at=now,
        paused_round_deadline=state.match.current_round.deadline,
        meeting_cooldown_until=meeting_cooldown_until,
        player_votes=(),
    )
    updated = replace(
        state,
        players=tuple(players),
        phase=GamePhase.MEETING_DISCUSSION,
        phase_deadline=discussion_deadline,
        match=updated_match,
    )
    return _accepted(
        updated,
        MeetingStarted(
            occurred_at=now,
            request_id=command.request_id,
            caller_player_id=command.player_id,
            discussion_deadline_at=discussion_deadline.due_at,
        ),
    )


def begin_player_vote(
    state: RoomState,
    now: datetime,
    vote_deadline: GameDeadline,
) -> TransitionOutcome:
    """End discussion and open the separate, timed player ballot."""

    _validate_now(now)
    if _room_unavailable(state, now):
        return _reject(state, RejectionCode.ROOM_CLOSED, "This room is closed.")
    if state.phase is not GamePhase.MEETING_DISCUSSION or state.match is None:
        return _reject(state, RejectionCode.WRONG_PHASE, "Discussion is not active.")
    if state.phase_deadline is None or state.phase_deadline.kind is not DeadlineKind.MEETING_DISCUSSION:
        return _reject(state, RejectionCode.INVALID_DEADLINE, "The discussion has no valid deadline.")
    if now < state.phase_deadline.due_at:
        return _reject(state, RejectionCode.DEADLINE_NOT_REACHED, "Discussion has not ended yet.")
    deadline_error = _validate_supplied_deadline(vote_deadline, DeadlineKind.PLAYER_VOTE, now)
    if deadline_error is not None:
        return _reject(state, deadline_error, "A future player-vote deadline is required.")

    updated_match = replace(state.match, player_votes=())
    updated = replace(
        state,
        phase=GamePhase.PLAYER_VOTE,
        phase_deadline=vote_deadline,
        match=updated_match,
    )
    return _accepted(
        updated,
        PlayerVotingStarted(occurred_at=now, request_id=None, deadline_at=vote_deadline.due_at),
    )


def _cast_player_vote(
    state: RoomState,
    command: CastPlayerVote,
    now: datetime,
) -> TransitionOutcome:
    if state.phase is not GamePhase.PLAYER_VOTE or state.match is None:
        return _reject(state, RejectionCode.WRONG_PHASE, "Player voting is not open.", command.request_id)
    if not _deadline_is_open(state, now):
        return _reject(state, RejectionCode.DEADLINE_PASSED, "The player-vote deadline has passed.", command.request_id)
    voter = _find_player(state, command.player_id, require_alive=True)
    if voter is None:
        return _reject(state, RejectionCode.PLAYER_NOT_CONNECTED, "Only a connected living player may vote.", command.request_id)
    if any(vote.voter_id == command.player_id for vote in state.match.player_votes):
        return _reject(state, RejectionCode.ALREADY_VOTED, "You have already cast a player vote.", command.request_id)
    if command.target_player_id is not None:
        target = _find_player(
            state,
            command.target_player_id,
            require_connected=False,
            require_alive=True,
        )
        if target is None:
            return _reject(state, RejectionCode.INVALID_VOTE_TARGET, "That player cannot be voted out.", command.request_id)

    vote = Vote(
        kind=VoteKind.PLAYER,
        voter_id=command.player_id,
        target_id=command.target_player_id,
        request_id=command.request_id,
        cast_at=now,
    )
    updated_match = replace(state.match, player_votes=(*state.match.player_votes, vote))
    updated = replace(state, match=updated_match)
    ballot_event = PlayerBallotStored(
        occurred_at=now,
        request_id=command.request_id,
        recipient_player_id=command.player_id,
        is_skip=command.target_player_id is None,
    )
    eligible = _eligible_connected_players(updated)
    all_voted = bool(eligible) and all(
        any(item.voter_id == player.player_id for item in updated_match.player_votes)
        for player in eligible
    )
    if not all_voted:
        return _accepted(updated, ballot_event)
    resolved = _resolve_player_vote(updated, now, request_id=command.request_id)
    if isinstance(resolved, TransitionRejected):
        return resolved
    return _accepted(resolved.state, ballot_event, *resolved.events)


def resolve_player_vote(
    state: RoomState,
    now: datetime,
    *,
    deadline_id: str | None = None,
) -> TransitionOutcome:
    """Resolve ballots once everyone eligible voted or the ballot deadline hit."""

    _validate_now(now)
    if _room_unavailable(state, now):
        return _reject(state, RejectionCode.ROOM_CLOSED, "This room is closed.")
    if state.phase is not GamePhase.PLAYER_VOTE or state.match is None:
        return _reject(state, RejectionCode.WRONG_PHASE, "Player voting is not active.")
    if state.phase_deadline is None or state.phase_deadline.kind is not DeadlineKind.PLAYER_VOTE:
        return _reject(state, RejectionCode.INVALID_DEADLINE, "The player vote has no valid deadline.")
    if deadline_id is not None and deadline_id != state.phase_deadline.deadline_id:
        return _reject(state, RejectionCode.STALE_DEADLINE, "This timeout belongs to an old vote.")
    eligible = _eligible_connected_players(state)
    all_voted = bool(eligible) and all(
        any(vote.voter_id == player.player_id for vote in state.match.player_votes)
        for player in eligible
    )
    if not all_voted and now < state.phase_deadline.due_at:
        return _reject(state, RejectionCode.VOTE_NOT_COMPLETE, "Player voting is still in progress.")
    return _resolve_player_vote(state, now, request_id=None)


def _resolve_player_vote(
    state: RoomState,
    now: datetime,
    *,
    request_id: str | None,
) -> TransitionOutcome:
    assert state.match is not None
    valid_targets = {
        player.player_id
        for player in state.players
        if player.is_alive and player.connection is not ConnectionStatus.DEPARTED
    }
    target_counts = Counter(
        vote.target_id
        for vote in state.match.player_votes
        if vote.target_id in valid_targets
    )
    skip_count = sum(vote.target_id is None for vote in state.match.player_votes)
    if target_counts:
        highest = max(target_counts.values())
        leaders = tuple(sorted(player_id for player_id, count in target_counts.items() if count == highest))
    else:
        leaders = ()
    was_tie = len(leaders) > 1
    ejected_id = leaders[0] if len(leaders) == 1 else None
    counts = tuple(sorted(target_counts.items()))

    events: list[GameEvent] = [
        PlayerVoteResolved(
            occurred_at=now,
            request_id=request_id,
            vote_counts=counts,
            skip_count=skip_count,
            ejected_player_id=ejected_id,
            was_tie=was_tie,
        )
    ]
    players = list(state.players)
    updated_match = state.match
    updated_phase = GamePhase.CODING_ROUND
    updated_deadline: GameDeadline | None = None

    if ejected_id is not None:
        target_index = _player_index(state, ejected_id)
        assert target_index is not None
        target = players[target_index]
        players[target_index] = replace(target, is_alive=False)
        events.append(PlayerEliminated(occurred_at=now, request_id=request_id, player_id=ejected_id))
        if target.role is PlayerRole.IMPOSTOR:
            result = MatchResult(
                winner=MatchWinner.CIVILIANS,
                reason=MatchEndReason.IMPOSTOR_EJECTED,
                round_number=state.match.round_number,
                ended_at=now,
            )
            updated_match = replace(
                state.match,
                result=result,
                player_votes=(),
                meeting_started_at=None,
                paused_round_deadline=None,
            )
            updated_phase = GamePhase.GAME_OVER
            events.append(
                MatchEnded(
                    occurred_at=now,
                    request_id=request_id,
                    winner=result.winner,
                    reason=result.reason,
                    round_number=result.round_number,
                )
            )
        else:
            updated_match, updated_deadline = _resume_round_after_meeting(state.match, now)
    else:
        updated_match, updated_deadline = _resume_round_after_meeting(state.match, now)

    updated = replace(
        state,
        players=tuple(players),
        phase=updated_phase,
        phase_deadline=updated_deadline,
        match=updated_match,
    )
    return _accepted(updated, *events)


def _resume_round_after_meeting(
    match: MatchState,
    now: datetime,
) -> tuple[MatchState, GameDeadline]:
    if (
        match.current_round is None
        or match.meeting_started_at is None
        or match.paused_round_deadline is None
    ):
        raise ValueError("meeting state is missing its paused coding deadline")
    pause_duration = now - match.meeting_started_at
    if pause_duration < timedelta(0):
        raise ValueError("meeting resolution time cannot precede meeting start")

    original = match.paused_round_deadline
    resumed_deadline = GameDeadline(
        deadline_id=f"{original.deadline_id}:resumed:{now.isoformat()}",
        kind=DeadlineKind.CODING_ROUND,
        due_at=original.due_at + pause_duration,
    )
    resumed_round = replace(match.current_round, deadline=resumed_deadline)
    updated_match = replace(
        match,
        current_round=resumed_round,
        player_votes=(),
        meeting_started_at=None,
        paused_round_deadline=None,
    )
    return updated_match, resumed_deadline


def record_source_revision(
    state: RoomState,
    source_revision_id: str,
    now: datetime,
) -> TransitionOutcome:
    """Accept a revision committed by the trusted editor coordinator.

    Edits are not game commands. The coordinator serializes this fact with
    runner results, so a result for the previous revision cannot win.
    """

    _validate_now(now)
    if _room_unavailable(state, now):
        return _reject(state, RejectionCode.ROOM_CLOSED, "This room is closed.")
    if state.phase is not GamePhase.CODING_ROUND or state.match is None or state.match.current_round is None:
        return _reject(state, RejectionCode.WRONG_PHASE, "Code can only change during a coding round.")
    if not _deadline_is_open(state, now):
        return _reject(state, RejectionCode.DEADLINE_PASSED, "The coding-round deadline has passed.")
    if not source_revision_id or not source_revision_id.strip():
        return _reject(state, RejectionCode.INVALID_SELECTION, "A source revision ID is required.")
    current = state.match.current_round
    if source_revision_id == current.current_source_revision_id:
        return _accepted(state)
    updated_round = replace(
        current,
        current_source_revision_id=source_revision_id,
        official_test_result=None,
    )
    updated = replace(state, match=replace(state.match, current_round=updated_round))
    return _accepted(
        updated,
        SourceRevisionChanged(
            occurred_at=now, request_id=None, source_revision_id=source_revision_id
        ),
    )


def record_verified_sabotage_objective(
    state: RoomState,
    objective_id: str,
    source_revision_id: str,
    now: datetime,
) -> TransitionOutcome:
    """Commit a trusted verifier's positive verdict for the current revision.

    The verifier itself belongs to the later runner phase. Its verdict must be
    authenticated by the coordinator; never expose this function as a player
    command or accept a browser-reported success flag.
    """

    _validate_now(now)
    if _room_unavailable(state, now):
        return _reject(state, RejectionCode.ROOM_CLOSED, "This room is closed.")
    if state.phase is not GamePhase.CODING_ROUND or state.match is None or state.match.current_round is None:
        return _reject(state, RejectionCode.WRONG_PHASE, "An objective cannot resolve in this phase.")
    if not _deadline_is_open(state, now):
        return _reject(state, RejectionCode.DEADLINE_PASSED, "The coding-round deadline has passed.")
    current = state.match.current_round
    if source_revision_id != current.current_source_revision_id:
        return _reject(state, RejectionCode.STALE_REVISION, "The objective verdict is for an older code revision.")
    index = next((i for i, item in enumerate(current.sabotage_objectives) if item.objective_id == objective_id), None)
    if index is None:
        return _reject(state, RejectionCode.INVALID_OBJECTIVE, "This objective is not assigned to the round.")
    impostor = next((player for player in state.players if player.role is PlayerRole.IMPOSTOR), None)
    if impostor is None or not impostor.is_alive:
        return _reject(state, RejectionCode.INVALID_SELECTION, "No active impostor is assigned.")
    if current.sabotage_objectives[index].status is ObjectiveStatus.COMPLETED:
        return _accepted(state)
    objectives = list(current.sabotage_objectives)
    objectives[index] = replace(
        objectives[index],
        status=ObjectiveStatus.COMPLETED,
        verified_revision_id=source_revision_id,
        completed_at=now,
    )
    updated_round = replace(current, sabotage_objectives=tuple(objectives))
    updated_match = replace(state.match, current_round=updated_round)
    events: list[GameEvent] = [
        SabotageObjectiveVerified(
            occurred_at=now,
            request_id=None,
            recipient_player_id=impostor.player_id,
            objective_id=objective_id,
            source_revision_id=source_revision_id,
        )
    ]
    if all(item.status is ObjectiveStatus.COMPLETED for item in objectives):
        result = MatchResult(
            winner=MatchWinner.IMPOSTOR,
            reason=MatchEndReason.SABOTAGE_OBJECTIVES_COMPLETED,
            round_number=current.number,
            ended_at=now,
        )
        updated_match = replace(updated_match, result=result)
        events.append(
            MatchEnded(
                occurred_at=now,
                request_id=None,
                winner=result.winner,
                reason=result.reason,
                round_number=result.round_number,
            )
        )
        return _accepted(
            replace(state, phase=GamePhase.GAME_OVER, phase_deadline=None, match=updated_match),
            *events,
        )
    return _accepted(replace(state, match=updated_match), *events)


def record_official_test_result(
    state: RoomState,
    result: OfficialTestResult,
    now: datetime,
) -> TransitionOutcome:
    """Commit a trusted test result only if it is timely and for current code."""

    _validate_now(now)
    if _room_unavailable(state, now):
        return _reject(state, RejectionCode.ROOM_CLOSED, "This room is closed.")
    if state.phase is not GamePhase.CODING_ROUND or state.match is None or state.match.current_round is None:
        return _reject(state, RejectionCode.WRONG_PHASE, "Official tests can only resolve during a coding round.")
    current_round = state.match.current_round
    if result.source_revision_id != current_round.current_source_revision_id:
        return _reject(state, RejectionCode.STALE_REVISION, "The test result is for an older code revision.")
    if current_round.official_test_result is not None and current_round.official_test_result.run_id == result.run_id:
        if current_round.official_test_result == result:
            return _accepted(state)
        return _reject(state, RejectionCode.DUPLICATE_REQUEST, "This runner ID has already been recorded with different results.")
    if result.completed_at > now:
        return _reject(state, RejectionCode.RESULT_FROM_FUTURE, "The test result completion time is in the future.")
    if result.completed_at < current_round.started_at:
        return _reject(state, RejectionCode.INVALID_SELECTION, "The test result predates this round.")
    if (
        not action_is_before_deadline(current_round.deadline, now)
        or not action_is_before_deadline(current_round.deadline, result.completed_at)
    ):
        return _reject(state, RejectionCode.DEADLINE_PASSED, "The round deadline has passed.")

    updated_round = replace(current_round, official_test_result=result)
    updated_match = replace(state.match, current_round=updated_round)
    accepted_event = OfficialTestResultAccepted(
        occurred_at=now,
        request_id=None,
        source_revision_id=result.source_revision_id,
        all_required_tests_passed=result.all_required_tests_passed,
    )
    if result.all_required_tests_passed:
        match_result = MatchResult(
            winner=MatchWinner.CIVILIANS,
            reason=MatchEndReason.REQUIRED_TESTS_PASSED,
            round_number=current_round.number,
            ended_at=now,
        )
        updated_match = replace(updated_match, result=match_result)
        updated = replace(
            state,
            phase=GamePhase.GAME_OVER,
            phase_deadline=None,
            match=updated_match,
        )
        return _accepted(
            updated,
            accepted_event,
            MatchEnded(
                occurred_at=now,
                request_id=None,
                winner=match_result.winner,
                reason=match_result.reason,
                round_number=match_result.round_number,
            ),
        )

    return _accepted(replace(state, match=updated_match), accepted_event)


def end_coding_round(
    state: RoomState,
    now: datetime,
    *,
    deadline_id: str,
) -> TransitionOutcome:
    """Apply an expired coding deadline once; a repeated callback is stale."""

    _validate_now(now)
    if _room_unavailable(state, now):
        return _reject(state, RejectionCode.ROOM_CLOSED, "This room is closed.")
    if state.phase is not GamePhase.CODING_ROUND or state.match is None or state.match.current_round is None:
        return _reject(state, RejectionCode.WRONG_PHASE, "No coding round is active.")
    deadline = state.match.current_round.deadline
    if deadline_id != deadline.deadline_id:
        return _reject(state, RejectionCode.STALE_DEADLINE, "This timeout belongs to an old round.")
    if not evaluate_deadline(deadline, now).is_due:
        return _reject(state, RejectionCode.DEADLINE_NOT_REACHED, "The coding-round deadline has not arrived.")

    current_round = state.match.current_round
    if current_round.number == MAX_ROUNDS:
        impostor = next(
            (player for player in state.players if player.role is PlayerRole.IMPOSTOR),
            None,
        )
        if impostor is None:
            return _reject(state, RejectionCode.INVALID_SELECTION, "The match has no assigned impostor.")
        if impostor.is_alive:
            result = MatchResult(
                winner=MatchWinner.IMPOSTOR,
                reason=MatchEndReason.FINAL_DEADLINE_SURVIVED,
                round_number=current_round.number,
                ended_at=now,
            )
            updated_match = replace(state.match, result=result)
            updated = replace(state, phase=GamePhase.GAME_OVER, phase_deadline=None, match=updated_match)
            return _accepted(
                updated,
                RoundEnded(occurred_at=now, request_id=None, round_number=current_round.number),
                MatchEnded(
                    occurred_at=now,
                    request_id=None,
                    winner=result.winner,
                    reason=result.reason,
                    round_number=result.round_number,
                ),
            )
        return _reject(state, RejectionCode.INVALID_SELECTION, "An eliminated impostor should already have ended the match.")

    updated = replace(state, phase=GamePhase.ROUND_RESULT, phase_deadline=None)
    return _accepted(
        updated,
        RoundEnded(occurred_at=now, request_id=None, round_number=current_round.number),
    )


def _request_test_run(
    state: RoomState,
    command: RequestOfficialTestRun,
    now: datetime,
) -> TransitionOutcome:
    if state.phase is not GamePhase.CODING_ROUND or state.match is None or state.match.current_round is None:
        return _reject(state, RejectionCode.WRONG_PHASE, "Tests can only be requested during a coding round.", command.request_id)
    if not _deadline_is_open(state, now):
        return _reject(state, RejectionCode.DEADLINE_PASSED, "The coding-round deadline has passed.", command.request_id)
    player = _find_player(state, command.player_id, require_alive=True)
    if player is None:
        return _reject(state, RejectionCode.PLAYER_NOT_CONNECTED, "Only a connected living player may request tests.", command.request_id)
    if command.source_revision_id != state.match.current_round.current_source_revision_id:
        return _reject(state, RejectionCode.STALE_REVISION, "Tests can only be requested for the current code revision.", command.request_id)
    return _accepted(
        state,
        OfficialTestRunRequested(
            occurred_at=now,
            request_id=command.request_id,
            player_id=command.player_id,
            source_revision_id=command.source_revision_id,
        ),
    )


def _send_chat(
    state: RoomState,
    command: SendChatMessage,
    now: datetime,
) -> TransitionOutcome:
    player = _find_player(state, command.player_id, require_alive=False)
    if player is None:
        return _reject(state, RejectionCode.PLAYER_NOT_CONNECTED, "Only a connected room member may chat.", command.request_id)
    return _accepted(
        state,
        ChatMessagePosted(
            occurred_at=now,
            request_id=command.request_id,
            player_id=command.player_id,
            message=command.message,
        ),
    )


def _leave_room(
    state: RoomState,
    command: LeaveRoom,
    now: datetime,
) -> TransitionOutcome:
    index = _player_index(state, command.player_id)
    if index is None or state.players[index].connection is not ConnectionStatus.CONNECTED:
        return _reject(state, RejectionCode.PLAYER_NOT_FOUND, "Player is not an active room member.", command.request_id)
    return _depart_player(state, command.player_id, now, request_id=command.request_id)


def _depart_player(
    state: RoomState,
    player_id: str,
    now: datetime,
    *,
    request_id: str | None,
) -> TransitionAccepted:
    index = _player_index(state, player_id)
    assert index is not None
    player = state.players[index]
    players = list(state.players)
    players[index] = replace(
        player,
        connection=ConnectionStatus.DEPARTED,
        reconnect_deadline=None,
        is_ready=False,
        is_alive=False,
    )
    events: list[GameEvent] = [
        PlayerDeparted(occurred_at=now, request_id=request_id, player_id=player_id)
    ]
    host_id = state.host_player_id
    closed = state.is_closed
    phase = state.phase
    phase_deadline = state.phase_deadline
    match = state.match
    if player_id == host_id:
        successors = [
            item for item in players
            if item.connection is not ConnectionStatus.DEPARTED and item.player_id != player_id
        ]
        if successors:
            successor = min(
                successors,
                key=lambda item: (item.connection is not ConnectionStatus.CONNECTED, item.joined_at),
            )
            events.append(
                HostTransferred(
                    occurred_at=now,
                    request_id=request_id,
                    previous_host_player_id=host_id,
                    new_host_player_id=successor.player_id,
                )
            )
            host_id = successor.player_id
        else:
            closed = True
            events.append(RoomClosed(occurred_at=now, request_id=request_id, room_code=state.room_code))

    if (
        player.role is PlayerRole.IMPOSTOR
        and match is not None
        and state.phase not in {GamePhase.GAME_OVER, GamePhase.LOBBY}
    ):
        result = MatchResult(
            winner=MatchWinner.CIVILIANS,
            reason=MatchEndReason.IMPOSTOR_DEPARTED,
            round_number=match.round_number,
            ended_at=now,
        )
        match = replace(
            match,
            result=result,
            player_votes=(),
            meeting_started_at=None,
            paused_round_deadline=None,
        )
        phase = GamePhase.GAME_OVER
        phase_deadline = None
        events.append(
            MatchEnded(
                occurred_at=now,
                request_id=request_id,
                winner=result.winner,
                reason=result.reason,
                round_number=result.round_number,
            )
        )
    elif (
        state.phase is GamePhase.CATEGORY_VOTE
        and sum(item.connection is not ConnectionStatus.DEPARTED for item in players) < MIN_PLAYERS
        and not closed
    ):
        # Roles were never assigned and the ballot can no longer form a match.
        closed = True
        phase_deadline = None
        events.append(RoomClosed(occurred_at=now, request_id=request_id, room_code=state.room_code))

    updated = replace(
        state,
        players=tuple(players),
        host_player_id=host_id,
        is_closed=closed,
        phase=phase,
        phase_deadline=None if closed else phase_deadline,
        match=match,
    )
    return _accepted(updated, *events)


def mark_player_disconnected(
    state: RoomState,
    player_id: str,
    reconnect_deadline: GameDeadline,
    now: datetime,
) -> TransitionOutcome:
    """Record a transport loss without immediately eliminating the player."""

    _validate_now(now)
    if _room_unavailable(state, now):
        return _reject(state, RejectionCode.ROOM_CLOSED, "This room is closed.")
    index = _player_index(state, player_id)
    if index is None or state.players[index].connection is ConnectionStatus.DEPARTED:
        return _reject(state, RejectionCode.PLAYER_NOT_FOUND, "Player is not an active room member.")
    if state.players[index].connection is ConnectionStatus.DISCONNECTED:
        return _accepted(state)
    error = _validate_supplied_deadline(reconnect_deadline, DeadlineKind.RECONNECT_GRACE, now)
    if error is not None:
        return _reject(state, error, "A future reconnect-grace deadline is required.")
    players = list(state.players)
    players[index] = replace(
        players[index],
        connection=ConnectionStatus.DISCONNECTED,
        reconnect_deadline=reconnect_deadline,
    )
    return _accepted(
        replace(state, players=tuple(players)),
        PlayerDisconnected(occurred_at=now, request_id=None, player_id=player_id),
    )


def restore_player_connection(
    state: RoomState,
    player_id: str,
    now: datetime,
) -> TransitionOutcome:
    """Restore the same player during grace after external credential checks."""

    _validate_now(now)
    if _room_unavailable(state, now):
        return _reject(state, RejectionCode.ROOM_CLOSED, "This room is closed.")
    index = _player_index(state, player_id)
    if index is None or state.players[index].connection is ConnectionStatus.DEPARTED:
        return _reject(state, RejectionCode.PLAYER_NOT_FOUND, "Player is not an active room member.")
    player = state.players[index]
    if player.connection is ConnectionStatus.CONNECTED:
        return _reject(state, RejectionCode.PLAYER_ALREADY_CONNECTED, "Player is already connected.")
    assert player.reconnect_deadline is not None
    if not action_is_before_deadline(player.reconnect_deadline, now):
        return _reject(state, RejectionCode.RECONNECT_GRACE_EXPIRED, "Reconnect grace has expired.")
    players = list(state.players)
    players[index] = replace(player, connection=ConnectionStatus.CONNECTED, reconnect_deadline=None)
    return _accepted(
        replace(state, players=tuple(players)),
        PlayerReconnected(occurred_at=now, request_id=None, player_id=player_id),
    )


def expire_reconnect_grace(
    state: RoomState,
    player_id: str,
    deadline_id: str,
    now: datetime,
) -> TransitionOutcome:
    """Apply a per-player grace timeout once; old callbacks are harmless."""

    _validate_now(now)
    if state.is_closed:
        return _reject(state, RejectionCode.ROOM_CLOSED, "This room is closed.")
    if now >= state.expires_at:
        return expire_room(state, now)
    index = _player_index(state, player_id)
    if index is None or state.players[index].connection is not ConnectionStatus.DISCONNECTED:
        return _reject(state, RejectionCode.STALE_DEADLINE, "No reconnect grace is pending.")
    evaluation = evaluate_deadline(
        state.players[index].reconnect_deadline,
        now,
        expected_id=deadline_id,
        expected_kind=DeadlineKind.RECONNECT_GRACE,
    )
    if evaluation.status is not DeadlineStatus.DUE:
        code = RejectionCode.RECONNECT_GRACE_OPEN if evaluation.status is DeadlineStatus.OPEN else RejectionCode.STALE_DEADLINE
        return _reject(state, code, "Reconnect grace has not expired or this callback is stale.")
    return _depart_player(state, player_id, now, request_id=None)


def _end_room(
    state: RoomState,
    command: EndRoom,
    now: datetime,
) -> TransitionOutcome:
    if command.player_id != state.host_player_id:
        return _reject(state, RejectionCode.NOT_HOST, "Only the host can close the room.", command.request_id)
    player = _find_player(state, command.player_id, require_alive=False)
    if player is None:
        return _reject(state, RejectionCode.PLAYER_NOT_CONNECTED, "The host must be connected to close the room.", command.request_id)
    if state.is_closed:
        return _reject(state, RejectionCode.ROOM_CLOSED, "This room is already closed.", command.request_id)
    updated = replace(state, is_closed=True, phase_deadline=None)
    return _accepted(
        updated,
        RoomClosed(occurred_at=now, request_id=command.request_id, room_code=state.room_code),
    )


def _request_rematch(
    state: RoomState,
    command: RequestRematch,
    now: datetime,
) -> TransitionOutcome:
    if state.phase is not GamePhase.GAME_OVER or state.match is None or state.match.result is None:
        return _reject(state, RejectionCode.MATCH_NOT_FINISHED, "A rematch can only be requested after a match ends.", command.request_id)
    player = _find_player(state, command.player_id, require_alive=False)
    if player is None:
        return _reject(state, RejectionCode.PLAYER_NOT_CONNECTED, "Only a connected room member may request a rematch.", command.request_id)
    if command.player_id in state.match.rematch_requests:
        return _accepted(state)
    requests = (*state.match.rematch_requests, command.player_id)
    updated_match = replace(
        state.match,
        rematch_requests=requests,
    )
    requested = RematchRequested(
        occurred_at=now, request_id=command.request_id, player_id=command.player_id
    )
    connected = tuple(
        player for player in state.players
        if player.connection is ConnectionStatus.CONNECTED
    )
    if len(connected) < MIN_PLAYERS or any(player.player_id not in requests for player in connected):
        return _accepted(replace(state, match=updated_match), requested)

    players = tuple(
        replace(player, role=None, is_alive=player.connection is not ConnectionStatus.DEPARTED,
                is_ready=False, emergency_meetings_used=0)
        for player in state.players
    )
    return _accepted(
        replace(state, players=players, phase=GamePhase.LOBBY, phase_deadline=None, match=None),
        requested,
        RematchStarted(occurred_at=now, request_id=None, room_code=state.room_code),
    )


def process_deadline(
    state: RoomState,
    deadline_id: str,
    now: datetime,
    *,
    selected_category_id: str | None = None,
    impostor_player_id: str | None = None,
    next_deadline: GameDeadline | None = None,
    next_round: RoundState | None = None,
) -> TransitionOutcome:
    """Process the room's current deadline; stale/repeated callbacks do nothing."""

    _validate_now(now)
    if now >= state.expires_at:
        return expire_room(state, now)
    deadline = state.phase_deadline
    evaluation = evaluate_deadline(deadline, now, expected_id=deadline_id)
    if evaluation.status in {DeadlineStatus.NO_DEADLINE, DeadlineStatus.STALE_ID}:
        return _reject(state, RejectionCode.STALE_DEADLINE, "This timeout is no longer current.")
    if not evaluation.is_due:
        return _reject(state, RejectionCode.DEADLINE_NOT_REACHED, "The deadline has not arrived.")

    if deadline.kind is DeadlineKind.CATEGORY_VOTE:
        if selected_category_id is None or impostor_player_id is None or next_deadline is None:
            return _reject(state, RejectionCode.INVALID_SELECTION, "Category, role, and role-reveal deadline are required to resolve this deadline.")
        return resolve_category_vote(
            state,
            now,
            selected_category_id=selected_category_id,
            impostor_player_id=impostor_player_id,
            role_reveal_deadline=next_deadline,
        )
    if deadline.kind is DeadlineKind.ROLE_REVEAL:
        if next_round is None:
            return _reject(state, RejectionCode.INVALID_SELECTION, "A selected challenge round is required after role reveal.")
        return start_coding_round(state, next_round, now)
    if deadline.kind is DeadlineKind.MEETING_DISCUSSION:
        if next_deadline is None:
            return _reject(state, RejectionCode.MISSING_DEADLINE, "A player-vote deadline is required.")
        return begin_player_vote(state, now, next_deadline)
    if deadline.kind is DeadlineKind.PLAYER_VOTE:
        return resolve_player_vote(state, now, deadline_id=deadline_id)
    if deadline.kind is DeadlineKind.CODING_ROUND:
        return end_coding_round(state, now, deadline_id=deadline_id)
    if deadline.kind is DeadlineKind.ROOM_EXPIRY:
        return expire_room(state, now)
    return _reject(state, RejectionCode.ACTION_NOT_SUPPORTED, "This deadline kind is not handled here.")


def expire_room(state: RoomState, now: datetime) -> TransitionOutcome:
    """Close a room at its absolute expiry, independent of its game phase."""

    _validate_now(now)
    if state.is_closed:
        return _reject(state, RejectionCode.ROOM_CLOSED, "This room is already closed.")
    if now < state.expires_at:
        return _reject(state, RejectionCode.DEADLINE_NOT_REACHED, "The room has not expired.")
    return _accepted(
        replace(state, is_closed=True, phase_deadline=None),
        RoomClosed(occurred_at=now, request_id=None, room_code=state.room_code),
    )
