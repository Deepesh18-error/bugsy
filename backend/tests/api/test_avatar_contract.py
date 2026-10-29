"""Player character choices remain public and survive room storage."""

import unittest
import json
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError

from app.api.schemas import CreateRoomRequest, JoinRoomRequest, build_room_response
from app.game.models import GamePhase, PlayerState, RoomState
from app.rooms.serialization import deserialize_room, serialize_room


class AvatarContractTests(unittest.TestCase):
    def test_rejects_unknown_character_id(self):
        with self.assertRaises(ValidationError):
            CreateRoomRequest(display_name="Ada", avatar_id="unknown")
        with self.assertRaises(ValidationError):
            JoinRoomRequest(display_name="Ada", room_code="ABCDEFG2", avatar_id="unknown")

    def test_character_is_preserved_and_visible_in_snapshot(self):
        now = datetime.now(timezone.utc)
        room = RoomState(
            room_code="ABCDEFG2", host_player_id="host",
            players=(PlayerState(player_id="host", display_name="Ada", joined_at=now,
                                 avatar_id="apollo-coder"),),
            created_at=now, expires_at=now + timedelta(hours=1),
            capacity=4, phase=GamePhase.LOBBY,
        )
        restored = deserialize_room(serialize_room(room))
        self.assertEqual(restored.players[0].avatar_id, "apollo-coder")
        response = build_room_response(restored, "host")
        self.assertEqual(response.room.players[0].avatar_id, "apollo-coder")

        legacy_payload = json.loads(serialize_room(room))
        del legacy_payload["room"]["players"][0]["avatar_id"]
        legacy = deserialize_room(json.dumps(legacy_payload).encode())
        self.assertEqual(legacy.players[0].avatar_id, "linux-builder")


if __name__ == "__main__":
    unittest.main()
