"""Build trusted jobs from the authorized room and persisted editor revision."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from uuid import uuid4

from app.challenges.loader import ChallengeLoadError, load_challenge
from app.game.commands import RequestOfficialTestRun
from app.game.models import GamePhase
from app.rooms.repository import RoomStorageError, StoredRoom, editor_document_id
from app.rooms.repository import RoomRepository
from app.runner.contracts import RunnerEnqueueReceipt, RunnerJob, RunnerTestCase
from app.runner.repository import RunnerRepository, RunnerStorageError


class RunnerUnavailable(RuntimeError):
    """Official execution cannot be accepted safely at this time."""


class RunnerQueueFull(RunnerUnavailable):
    """The bounded official-test queue has reached its configured capacity."""


class RunnerService:
    """Create immutable, server-derived runner jobs; never accept source in a command."""

    def __init__(
        self,
        rooms: RoomRepository,
        runner: RunnerRepository,
        *,
        enabled: bool = True,
    ) -> None:
        self._rooms = rooms
        self._runner = runner
        self._enabled = enabled

    async def enqueue_for_request(
        self, stored: StoredRoom, command: RequestOfficialTestRun, now: datetime
    ) -> RunnerEnqueueReceipt:
        """Queue a manual request through the shared revision-coalescing path."""

        return await self.enqueue_for_revision(
            stored,
            player_id=command.player_id,
            request_id=command.request_id,
            source_revision_id=command.source_revision_id,
            now=now,
        )

    async def enqueue_for_revision(
        self,
        stored: StoredRoom,
        *,
        player_id: str,
        request_id: str,
        source_revision_id: str,
        now: datetime,
    ) -> RunnerEnqueueReceipt:
        """Shared entry point for manual and debounced automatic test triggers.

        Redis deduplicates the immutable room/match/round/revision/source/test
        identity, not the triggering request ID. Thus a manual click and an
        automatic trigger for the same saved revision share one runner job.
        """
        if not self._enabled:
            raise RunnerUnavailable("Official test execution is not configured.")
        state = stored.state
        match = state.match
        current = match.current_round if match is not None else None
        if (
            state.phase is not GamePhase.CODING_ROUND
            or match is None
            or match.match_id is None
            or current is None
            or source_revision_id != current.current_source_revision_id
            or current.deadline.due_at <= now
            or not any(
                player.player_id == player_id and player.is_alive
                and player.connection.value == "connected"
                for player in state.players
            )
        ):
            raise RunnerUnavailable("The requested code revision is no longer eligible for testing.")

        loaded = load_challenge(current.challenge_id, current.challenge_version)
        if loaded.content_digest != current.challenge_content_digest:
            raise RunnerUnavailable("The pinned challenge content changed.")

        document_id = editor_document_id(state)
        if document_id is None:
            raise RunnerUnavailable("The current editor document is unavailable.")
        document = await self._rooms.load_editor_document(document_id)
        if document is None and current.current_source_revision_id.startswith("seed-"):
            source = loaded.challenge.starter_code
        elif document is None:
            raise RunnerUnavailable("The saved editor revision is unavailable.")
        elif document.revision_id != current.current_source_revision_id:
            raise RunnerUnavailable("The saved editor revision does not match the room.")
        else:
            source = document.source

        try:
            tests = tuple(
                RunnerTestCase(
                    test_id=test.id,
                    test_definition_id=test.test_definition_id,
                    required_for_civilian_win=test.required_for_civilian_win,
                )
                for test in loaded.challenge.tests
            )
            identity = {
                "room": state.room_code,
                "match": match.match_id,
                "round": current.number,
                "deadline": current.deadline.deadline_id,
                "challenge_digest": loaded.content_digest,
                "revision": current.current_source_revision_id,
                "source_sha256": sha256(source.encode("utf-8")).hexdigest(),
                "tests": [item.model_dump(mode="json") for item in tests],
            }
            dedupe_key = sha256(
                json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            job = RunnerJob(
                run_id=uuid4().hex,
                room_code=state.room_code,
                match_id=match.match_id,
                round_number=current.number,
                deadline_id=current.deadline.deadline_id,
                challenge_id=loaded.challenge.id,
                challenge_version=loaded.challenge.version,
                challenge_content_digest=loaded.content_digest,
                runtime_policy=loaded.challenge.runtime_policy,
                source_revision_id=current.current_source_revision_id,
                source=source,
                requested_by_player_id=player_id,
                request_id=request_id,
                requested_at=now,
                tests=tests,
                dedupe_key=dedupe_key,
            )
            receipt = await self._runner.enqueue_job(job)
        except (ValueError, ChallengeLoadError) as exc:
            raise RunnerUnavailable("The challenge cannot be prepared for official testing.") from exc
        except (RoomStorageError, RunnerStorageError) as exc:
            raise RunnerUnavailable("Official test storage is unavailable.") from exc
        if receipt.run_id is None:
            raise RunnerQueueFull("The official test queue is full.")
        return receipt
