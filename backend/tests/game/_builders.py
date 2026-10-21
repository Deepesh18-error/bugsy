"""Small domain-object builders shared by the rule-level tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.game.models import (
    ConnectionStatus,
    DeadlineKind,
    GameDeadline,
    GamePhase,
    MatchState,
    PlayerRole,
    PlayerState,
    RoomState,
    RoundState,
)


NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
PLAYER_IDS = ("p1", "p2", "p3", "p4")


def make_players(
    *,
    ready: bool = False,
    roles: tuple[PlayerRole, ...] | None = None,
    disconnected: frozenset[str] = frozenset(),
    alive: frozenset[str] = frozenset(),
) -> tuple[PlayerState, ...]:
    if roles is None:
        roles = (
            PlayerRole.CIVILIAN,
            PlayerRole.CIVILIAN,
            PlayerRole.CIVILIAN,
            PlayerRole.IMPOSTOR,
        )
    result = []
    for index, player_id in enumerate(PLAYER_IDS):
        connection = (
            ConnectionStatus.DISCONNECTED
            if player_id in disconnected
            else ConnectionStatus.CONNECTED
        )
        result.append(
            PlayerState(
                player_id=player_id,
                display_name=f"Player {player_id}",
                joined_at=NOW + timedelta(seconds=index),
                connection=connection,
                is_ready=ready,
                is_alive=player_id not in alive,
                role=roles[index],
                reconnect_deadline=(
                    make_deadline(
                        f"reconnect-{player_id}",
                        DeadlineKind.RECONNECT_GRACE,
                        NOW + timedelta(seconds=60),
                    )
                    if player_id in disconnected else None
                ),
            )
        )
    return tuple(result)


def make_deadline(
    deadline_id: str,
    kind: DeadlineKind,
    due_at: datetime,
) -> GameDeadline:
    return GameDeadline(deadline_id=deadline_id, kind=kind, due_at=due_at)


def make_lobby(
    *,
    now: datetime = NOW,
    ready: bool = False,
    players: tuple[PlayerState, ...] | None = None,
    deadline: GameDeadline | None = None,
) -> RoomState:
    return RoomState(
        room_code="TEST42",
        host_player_id="p1",
        players=players if players is not None else make_players(ready=ready),
        created_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
        phase=GamePhase.LOBBY,
        capacity=5,
        phase_deadline=deadline,
    )


def make_round(
    *,
    number: int = 1,
    started_at: datetime = NOW,
    due_at: datetime | None = None,
) -> RoundState:
    if due_at is None:
        due_at = started_at + timedelta(seconds=120)
    return RoundState(
        number=number,
        category_id="object-oriented",
        challenge_id=f"oop.counter.round{number}",
        challenge_version="1.0.0",
        challenge_content_digest="sha256:fixture-digest",
        started_at=started_at,
        deadline=make_deadline(
            f"coding-{number}", DeadlineKind.CODING_ROUND, due_at
        ),
        current_source_revision_id="revision-1",
    )


def make_coding_room(
    *,
    round_number: int = 1,
    now: datetime = NOW,
    due_at: datetime | None = None,
    players: tuple[PlayerState, ...] | None = None,
) -> RoomState:
    round_state = make_round(number=round_number, started_at=now, due_at=due_at)
    return RoomState(
        room_code="TEST42",
        host_player_id="p1",
        players=players if players is not None else make_players(),
        created_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
        phase=GamePhase.CODING_ROUND,
        capacity=5,
        phase_deadline=round_state.deadline,
        match=MatchState(
            round_number=round_number,
            selected_category_id="object-oriented",
            current_round=round_state,
        ),
    )


def make_voting_room(
    *,
    now: datetime = NOW,
    due_at: datetime | None = None,
    players: tuple[PlayerState, ...] | None = None,
) -> RoomState:
    """Build a player-vote phase entered from a paused coding round."""

    if due_at is None:
        due_at = now + timedelta(seconds=30)
    meeting_started_at = now - timedelta(seconds=10)
    round_state = make_round(
        started_at=NOW,
        due_at=NOW + timedelta(seconds=120),
    )
    vote_deadline = make_deadline(
        "vote-1", DeadlineKind.PLAYER_VOTE, due_at
    )
    return RoomState(
        room_code="TEST42",
        host_player_id="p1",
        players=players if players is not None else make_players(),
        created_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
        phase=GamePhase.PLAYER_VOTE,
        capacity=5,
        phase_deadline=vote_deadline,
        match=MatchState(
            round_number=1,
            selected_category_id="object-oriented",
            current_round=round_state,
            meeting_started_at=meeting_started_at,
            paused_round_deadline=round_state.deadline,
            meeting_cooldown_until=NOW + timedelta(minutes=5),
        ),
    )


def make_discussion_room(*, now: datetime = NOW) -> RoomState:
    round_state = make_round(
        started_at=NOW,
        due_at=NOW + timedelta(seconds=120),
    )
    discussion_deadline = make_deadline(
        "discussion-1",
        DeadlineKind.MEETING_DISCUSSION,
        now + timedelta(seconds=15),
    )
    return RoomState(
        room_code="TEST42",
        host_player_id="p1",
        players=make_players(),
        created_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
        phase=GamePhase.MEETING_DISCUSSION,
        phase_deadline=discussion_deadline,
        match=MatchState(
            round_number=1,
            selected_category_id="object-oriented",
            current_round=round_state,
            meeting_started_at=now - timedelta(seconds=5),
            paused_round_deadline=round_state.deadline,
            meeting_cooldown_until=now + timedelta(minutes=5),
        ),
    )
