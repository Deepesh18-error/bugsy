"""FastAPI editor gateway, coordinator, and repository in one offline flow."""

import base64
import json
import unittest
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

from app.api.editor import (
    CommitRequest, DocumentRequest, InitializeRequest, authorize_editor,
    commit_editor, editor_history, initialize_editor,
)
from app.challenges.loader import load_challenge
from app.realtime.coordinator import RoomCoordinator
from app.rooms.redis_repository import RedisRoomRepository
from app.rooms.repository import editor_document_id
from app.rooms.serialization import serialize_room
from app.rooms.service import AuthenticatedGuest, RoomServiceError

from _support import NOW, coding_room, immediate_test, stored_room
from test_redis_editor_repository import AtomicRedisFake


Y_STATE = base64.b64encode(b"candidate-yjs-state").decode()


class GuestService:
    def __init__(self, repository):
        self.repository = repository

    async def authenticate_player(self, credential):
        if credential != "good-cookie":
            raise RoomServiceError("SESSION_INVALID", "Invalid session.", 401)
        stored = await self.repository.load_room("TEST42")
        return AuthenticatedGuest(stored.state, "p1", NOW + timedelta(hours=1), stored.sequence)


class Connections:
    def __init__(self):
        self.events = []

    async def broadcast(self, room_code, event):
        self.events.append(event)

    async def send_private(self, room_code, player_id, event):
        self.events.append(event)


def response_data(response):
    return json.loads(response.body)


class EditorIntegrationTests(unittest.TestCase):
    def setUp(self):
        loaded = load_challenge("oop.counter", "1.0.0")
        room = coding_room()
        current = replace(room.match.current_round,
                          challenge_content_digest=loaded.content_digest)
        room = replace(room, match=replace(room.match, current_round=current))
        self.stored = stored_room(room)
        self.client = AtomicRedisFake(self.stored)
        self.repository = RedisRoomRepository(self.client)
        self.connections = Connections()
        self.coordinator = RoomCoordinator(self.repository, self.connections)
        self.document_id = editor_document_id(room)
        self.request = SimpleNamespace(
            headers={"x-editor-service-key": "private-service-key", "origin": "http://127.0.0.1:5173"},
            cookies={"codemafia_guest": "good-cookie"},
            app=SimpleNamespace(state=SimpleNamespace(
                editor_service_key="private-service-key",
                allowed_origins=("http://127.0.0.1:5173",),
                room_service=GuestService(self.repository), room_repository=self.repository,
                room_coordinator=self.coordinator,
            )),
        )

    @immediate_test
    async def test_auth_initialize_commit_recover_and_restore(self):
        document = DocumentRequest(document_id=self.document_id)
        before = response_data(await authorize_editor(document, self.request))
        self.assertEqual(before["revision_id"], "seed-a")
        self.assertIsNone(before["y_state"])
        self.assertNotIn("reference_solution", before)

        seeded = await initialize_editor(
            InitializeRequest(document_id=self.document_id, y_state=Y_STATE), self.request)
        self.assertEqual(seeded.status_code, 200)
        first = await commit_editor(CommitRequest(
            document_id=self.document_id, previous_revision_id="seed-a",
            source="fixed once", y_state=Y_STATE), self.request)
        self.assertEqual(first.status_code, 200)
        first_id = response_data(first)["revision_id"]
        second = await commit_editor(CommitRequest(
            document_id=self.document_id, previous_revision_id=first_id,
            source="broken again", y_state=Y_STATE), self.request)
        self.assertEqual(second.status_code, 200)
        second_id = response_data(second)["revision_id"]

        invalid = await commit_editor(CommitRequest(
            document_id=self.document_id, previous_revision_id=second_id,
            source="invented", y_state=Y_STATE,
            restored_from_revision_id=first_id), self.request)
        self.assertEqual(invalid.status_code, 409)
        restored = await commit_editor(CommitRequest(
            document_id=self.document_id, previous_revision_id=second_id,
            source="fixed once", y_state=Y_STATE,
            restored_from_revision_id=first_id), self.request)
        self.assertEqual(restored.status_code, 200)

        after = response_data(await editor_history(document, self.request))
        self.assertEqual(after["history"][-1]["restored_from_revision_id"], first_id)
        restarted = RedisRoomRepository(self.client)
        recovered = await restarted.load_room("TEST42")
        saved_document = await restarted.load_editor_document(self.document_id)
        self.assertEqual(recovered.state.match.current_round.current_source_revision_id,
                         saved_document.revision_id)
        self.assertEqual(saved_document.source, "fixed once")
        self.assertIn("SourceRevisionRestored", [event.name for event in self.connections.events])
        self.assertNotIn("fixed once", json.dumps([event.model_dump() for event in self.connections.events]))

    @immediate_test
    async def test_stale_scope_and_mismatched_revisions_fail_closed(self):
        stale = await authorize_editor(DocumentRequest(document_id="TEST42:old-match:1"), self.request)
        self.assertEqual(stale.status_code, 403)
        self.request.headers["x-editor-service-key"] = "wrong"
        self.assertEqual((await authorize_editor(
            DocumentRequest(document_id=self.document_id), self.request)).status_code, 403)
        self.request.headers["x-editor-service-key"] = "private-service-key"
        await initialize_editor(InitializeRequest(document_id=self.document_id, y_state=Y_STATE), self.request)
        changed = replace(self.stored.state.match.current_round, current_source_revision_id="rev-other")
        state = replace(self.stored.state, match=replace(self.stored.state.match, current_round=changed))
        self.client.values["codemafia:v1:room:TEST42"] = serialize_room(state)
        self.assertEqual((await authorize_editor(
            DocumentRequest(document_id=self.document_id), self.request)).status_code, 409)


if __name__ == "__main__":
    unittest.main()
