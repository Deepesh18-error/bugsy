"""Real challenge content with in-memory storage for runner boundary tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from app.challenges.loader import load_challenge
from app.game.models import (
    DeadlineKind, GameDeadline, GamePhase, MatchState, PlayerRole,
    PlayerState, RoomState, RoundState,
)
from app.rooms.repository import EditorDocument, StoredRoom, editor_document_id
from app.rooms.serialization import serialize_room
from app.runner.contracts import RunnerEnqueueReceipt, RunnerQueueState


NOW = datetime.now(timezone.utc).replace(microsecond=0)
LOADED = load_challenge("oop.counter", "1.0.0")
KEY = "test-runner-signing-key-at-least-thirty-two-bytes"


def run_immediate(coroutine):
    """Drive fake I/O without opening a socket-backed Windows event loop."""
    try:
        coroutine.send(None)
    except StopIteration as result:
        return result.value
    raise AssertionError("The fake runner operation unexpectedly yielded.")


def coding_room(*, revision: str = "revision-1") -> RoomState:
    deadline = GameDeadline("deadline-1", DeadlineKind.CODING_ROUND, NOW + timedelta(minutes=5))
    current = RoundState(
        number=1, category_id="object-oriented", challenge_id=LOADED.challenge.id,
        challenge_version=LOADED.challenge.version,
        challenge_content_digest=LOADED.content_digest,
        started_at=NOW - timedelta(seconds=5), deadline=deadline,
        current_source_revision_id=revision,
    )
    players = tuple(PlayerState(
        player_id=f"player-{index}", display_name=f"Player {index}",
        joined_at=NOW - timedelta(minutes=1),
        role=PlayerRole.IMPOSTOR if index == 4 else PlayerRole.CIVILIAN,
    ) for index in range(1, 5))
    return RoomState(
        room_code="TEST42", host_player_id="player-1", players=players,
        created_at=NOW - timedelta(minutes=2), expires_at=NOW + timedelta(hours=1),
        phase=GamePhase.CODING_ROUND, capacity=5, phase_deadline=deadline,
        match=MatchState(match_id="match-1", round_number=1,
                         selected_category_id="object-oriented", current_round=current),
    )


class FakeRooms:
    def __init__(self, state: RoomState, source: str | None = None) -> None:
        self.stored = StoredRoom(state, serialize_room(state, sequence=0), 0)
        self.document = EditorDocument(
            revision_id=state.match.current_round.current_source_revision_id,
            source=source or LOADED.challenge.starter_code, y_state="eA==",
        )
        self.commits = 0

    async def load_room(self, room_code: str):
        return self.stored if self.stored.state.room_code == room_code else None

    async def load_editor_document(self, document_id: str):
        return self.document if document_id == editor_document_id(self.stored.state) else None

    async def compare_and_swap(self, previous, updated, *, advance_sequence=False, **_):
        if previous is not self.stored:
            return False
        sequence = previous.sequence + int(previous.state != updated or advance_sequence)
        self.stored = StoredRoom(updated, serialize_room(updated, sequence=sequence), sequence)
        self.commits += 1
        return True

    def change_revision(self, revision: str) -> None:
        state = self.stored.state
        current = replace(state.match.current_round, current_source_revision_id=revision)
        updated = replace(state, match=replace(state.match, current_round=current))
        self.stored = StoredRoom(updated, serialize_room(updated, sequence=self.stored.sequence + 1),
                                 self.stored.sequence + 1)


class FakeRunner:
    def __init__(self) -> None:
        self.job = None
        self.released = []

    async def enqueue_job(self, job):
        self.job = job
        return RunnerEnqueueReceipt(state=RunnerQueueState.ENQUEUED,
                                    run_id=job.run_id, stream_id="1-0")

    async def load_job(self, run_id):
        return self.job if self.job and self.job.run_id == run_id else None

    async def release_deduplication(self, job):
        self.released.append(job.run_id)


class FakeConnections:
    def __init__(self) -> None:
        self.public = []
        self.private = []

    async def broadcast(self, room_code, event):
        self.public.append((room_code, event))

    async def send_private(self, room_code, player_id, event):
        self.private.append((room_code, player_id, event))
