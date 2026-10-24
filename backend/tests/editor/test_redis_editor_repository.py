"""Exercise the Redis repository contract with an atomic Lua-shaped fake."""

import base64
import unittest

from app.rooms.redis_repository import RedisRoomRepository, _COMMIT_EDITOR, _INIT_EDITOR
from app.rooms.repository import editor_document_id

from _support import NOW, immediate_test, stored_room, updated_room


Y_STATE = base64.b64encode(b"yjs-state").decode()


class AtomicRedisFake:
    """The eval method models the two editor Lua scripts as indivisible writes."""

    def __init__(self, room):
        self.values = {f"codemafia:v1:room:{room.state.room_code}": room.raw}
        self.expiries = {}

    async def get(self, key):
        return self.values.get(key)

    async def eval(self, script, count, room_key, document_key, *args):
        assert count == 2
        if script == _INIT_EDITOR:
            previous_room, document, expiry = args
            if self.values.get(room_key) != previous_room or document_key in self.values:
                return 0
            self.values[document_key] = document
            self.expiries[document_key] = expiry
            return 1
        assert script == _COMMIT_EDITOR
        previous_room, updated_room, prior_revision, document, expiry = args
        if self.values.get(room_key) != previous_room:
            return 0
        import json
        prior = self.values.get(document_key)
        if prior is None or json.loads(prior)["revision_id"] != prior_revision:
            return 0
        self.values[room_key] = updated_room
        self.values[document_key] = document
        self.expiries[room_key] = self.expiries[document_key] = expiry
        return 1


class RedisEditorRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.original = stored_room()
        self.client = AtomicRedisFake(self.original)
        self.repository = RedisRoomRepository(self.client)
        self.document_id = editor_document_id(self.original.state)

    @immediate_test
    async def test_initialization_is_single_writer_and_restart_recovers_document(self):
        self.assertTrue(await self.repository.initialize_editor_document(
            self.original, document_id=self.document_id, source="starter", y_state=Y_STATE))
        self.assertFalse(await self.repository.initialize_editor_document(
            self.original, document_id=self.document_id, source="different", y_state=Y_STATE))
        restarted = RedisRoomRepository(self.client)
        self.assertEqual((await restarted.load_editor_document(self.document_id)).source, "starter")
        self.assertEqual((await restarted.load_room("TEST42")).state, self.original.state)

    @immediate_test
    async def test_room_and_document_revision_commit_together(self):
        await self.repository.initialize_editor_document(
            self.original, document_id=self.document_id, source="starter", y_state=Y_STATE)
        updated = updated_room(self.original.state, "rev-2")
        self.assertTrue(await self.repository.commit_editor_document(
            self.original, updated, document_id=self.document_id,
            previous_revision_id="seed-a", revision_id="rev-2", source="edited",
            y_state=Y_STATE, author_player_id="p2", recorded_at=NOW))
        recovered = RedisRoomRepository(self.client)
        room = await recovered.load_room("TEST42")
        document = await recovered.load_editor_document(self.document_id)
        self.assertEqual(room.state.match.current_round.current_source_revision_id, document.revision_id)
        self.assertEqual(room.sequence, 1)
        self.assertEqual(document.history[-1].author_player_id, "p2")
        self.assertEqual(self.client.expiries[f"codemafia:v1:room:TEST42"],
                         self.client.expiries[f"codemafia:v1:editor:{self.document_id}"])

    @immediate_test
    async def test_stale_second_writer_changes_neither_value(self):
        await self.repository.initialize_editor_document(
            self.original, document_id=self.document_id, source="starter", y_state=Y_STATE)
        first = updated_room(self.original.state, "rev-2")
        self.assertTrue(await self.repository.commit_editor_document(
            self.original, first, document_id=self.document_id,
            previous_revision_id="seed-a", revision_id="rev-2", source="first",
            y_state=Y_STATE, author_player_id="p1", recorded_at=NOW))
        second = updated_room(self.original.state, "rev-3")
        self.assertFalse(await self.repository.commit_editor_document(
            self.original, second, document_id=self.document_id,
            previous_revision_id="seed-a", revision_id="rev-3", source="second",
            y_state=Y_STATE, author_player_id="p2", recorded_at=NOW))
        self.assertEqual((await self.repository.load_editor_document(self.document_id)).source, "first")
        self.assertEqual((await self.repository.load_room("TEST42")).state, first)

    @immediate_test
    async def test_other_round_document_is_rejected_before_write(self):
        with self.assertRaises(ValueError):
            await self.repository.initialize_editor_document(
                self.original, document_id="TEST42:old-match:1", source="starter", y_state=Y_STATE)


if __name__ == "__main__":
    unittest.main()
