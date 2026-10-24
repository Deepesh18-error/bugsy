"""Durable editor document format and byte-budget checks."""

import base64
import json
import unittest
from datetime import datetime, timezone

from app.rooms.repository import (
    EditorDocument, EditorRevision, MAX_EDITOR_HISTORY_BYTES, RoomStorageError,
)
from app.rooms.serialization import deserialize_editor_document, serialize_editor_document


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
Y_STATE = base64.b64encode(b"sample-yjs-state").decode()


class DocumentStorageTests(unittest.TestCase):
    def test_versioned_round_trip_preserves_restore_provenance(self):
        document = EditorDocument("rev-2", "fixed", Y_STATE, (
            EditorRevision("rev-1", "broken", "p1", NOW),
            EditorRevision("rev-2", "fixed", "p2", NOW, "rev-1"),
        ))
        raw = serialize_editor_document(document)
        self.assertEqual(json.loads(raw)["storage_version"], 1)
        self.assertEqual(deserialize_editor_document(raw), document)

    def test_unversioned_record_is_recovered(self):
        legacy = {"revision_id": "rev-1", "source": "old", "y_state": Y_STATE,
                  "history": [{"revision_id": "rev-1", "source": "old",
                               "author_player_id": "p1", "recorded_at": NOW.isoformat()}]}
        recovered = deserialize_editor_document(json.dumps(legacy).encode())
        self.assertEqual(recovered.history[0].restored_from_revision_id, None)
        self.assertEqual(recovered.source, "old")

    def test_unversioned_history_is_trimmed_to_current_limits(self):
        entries = [{"revision_id": f"rev-{number}", "source": "old",
                    "author_player_id": "p1", "recorded_at": NOW.isoformat()}
                   for number in range(35)]
        legacy = {"revision_id": "rev-34", "source": "old", "y_state": Y_STATE,
                  "history": entries}
        recovered = deserialize_editor_document(json.dumps(legacy).encode())
        self.assertEqual(len(recovered.history), 30)
        self.assertEqual(recovered.history[0].revision_id, "rev-5")

    def test_history_is_pruned_by_count_and_bytes_without_dropping_current_source(self):
        document = EditorDocument("seed-a", "", Y_STATE)
        for number in range(35):
            revision = EditorRevision(f"rev-{number}", "x" * 40_000, "p1", NOW)
            document = document.append_revision(revision, Y_STATE)
        self.assertLess(len(document.history), 30)
        self.assertLessEqual(sum(len(entry.source.encode()) for entry in document.history),
                             MAX_EDITOR_HISTORY_BYTES)
        self.assertEqual(document.history[-1].revision_id, "rev-34")
        self.assertEqual(document.source, "x" * 40_000)

    def test_malformed_or_unknown_storage_is_rejected(self):
        document = EditorDocument("rev-1", "text", Y_STATE)
        invalid = [
            b'{"storage_version":2}',
            serialize_editor_document(document).replace(b'"revision_id":"rev-1"',
                                                        b'"revision_id":"bad id"'),
            b"not json",
        ]
        for raw in invalid:
            with self.subTest(raw=raw[:50]), self.assertRaises(RoomStorageError):
                deserialize_editor_document(raw)

    def test_invalid_yjs_and_oversized_source_are_rejected(self):
        with self.assertRaises(ValueError):
            EditorDocument("rev-1", "x", "not base64")
        with self.assertRaises(ValueError):
            EditorDocument("rev-1", "é" * 40_000, Y_STATE)


if __name__ == "__main__":
    unittest.main()
