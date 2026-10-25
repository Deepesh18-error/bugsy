"""Small live-round fixtures for editor storage and gateway checks."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from app.challenges.loader import load_challenge
from app.game.models import (
    DeadlineKind, GameDeadline, GamePhase, MatchState, PlayerRole,
    PlayerState, RoomState, RoundState,
)
from app.rooms.repository import StoredRoom
from app.rooms.serialization import serialize_room


NOW = datetime.now(timezone.utc).replace(microsecond=0)


def coding_room(*, revision_id: str = "seed-a", source_result=None) -> RoomState:
    loaded = load_challenge("oop.counter", "1.0.0")
    deadline = GameDeadline("coding-a", DeadlineKind.CODING_ROUND, NOW + timedelta(minutes=10))
    current = RoundState(
        number=1, category_id="object-oriented", challenge_id="oop.counter",
        challenge_version="1.0.0", challenge_content_digest=loaded.content_digest,
        started_at=NOW - timedelta(seconds=5), deadline=deadline,
        current_source_revision_id=revision_id, official_test_result=source_result,
    )
    players = tuple(PlayerState(
        player_id=f"p{index}", display_name=f"Player {index}",
        joined_at=NOW - timedelta(minutes=2), role=(PlayerRole.IMPOSTOR if index == 4 else PlayerRole.CIVILIAN),
    ) for index in range(1, 5))
    return RoomState(
        room_code="TEST42", host_player_id="p1", players=players,
        created_at=NOW - timedelta(minutes=3), expires_at=NOW + timedelta(hours=1),
        phase=GamePhase.CODING_ROUND, capacity=5, phase_deadline=deadline,
        match=MatchState(match_id="match-a", round_number=1,
                         selected_category_id="object-oriented", current_round=current),
    )


def stored_room(state: RoomState | None = None, sequence: int = 0) -> StoredRoom:
    state = state or coding_room()
    return StoredRoom(state, serialize_room(state, sequence=sequence), sequence)


def updated_room(state: RoomState, revision_id: str) -> RoomState:
    current = replace(state.match.current_round, current_source_revision_id=revision_id)
    return replace(state, match=replace(state.match, current_round=current))


def run_immediate(coroutine):
    """Drive fake-I/O coroutines without a Windows event loop."""

    try:
        coroutine.send(None)
    except StopIteration as result:
        return result.value
    raise AssertionError("The offline editor check unexpectedly yielded.")


def immediate_test(async_test):
    def synchronous_test(self):
        return run_immediate(async_test(self))
    return synchronous_test
