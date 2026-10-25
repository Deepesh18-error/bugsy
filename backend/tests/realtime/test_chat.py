"""Durable chat rules, timestamps, phase limits, and per-player rate limits."""

from dataclasses import replace
from datetime import timedelta
import unittest

from app.api.websocket import room_websocket
from app.game.commands import SendChatMessage
from app.game.models import DeadlineKind, GameDeadline, GamePhase, MatchState
from app.game.outcomes import RejectionCode, TransitionAccepted, TransitionRejected
from app.game.transitions import apply_command
from app.realtime.coordinator import RoomCoordinator
from app.realtime.snapshots import project_event
from app.rooms.serialization import deserialize_room, serialize_room
from _support import (
    DISCONNECT, NOW, FakeRepository, FakeService, FakeSocket, make_room, run_socket, text_frame,
)


def wire_chat(request_id: str, message: str) -> dict[str, object]:
    return {
        "version": 1,
        "type": "command",
        "request_id": request_id,
        "action": {"name": "send_chat_message", "message": message},
    }


def live_room_in_phase(phase: GamePhase, *, due_at=None):
    room = make_room()
    timed_phases = {
        GamePhase.CATEGORY_VOTE: DeadlineKind.CATEGORY_VOTE,
        GamePhase.ROLE_REVEAL: DeadlineKind.ROLE_REVEAL,
        GamePhase.CODING_ROUND: DeadlineKind.CODING_ROUND,
        GamePhase.MEETING_DISCUSSION: DeadlineKind.MEETING_DISCUSSION,
        GamePhase.PLAYER_VOTE: DeadlineKind.PLAYER_VOTE,
    }
    deadline = None
    if phase in timed_phases:
        deadline = GameDeadline(
            f"{phase.value}-deadline",
            timed_phases[phase],
            due_at or NOW + timedelta(seconds=30),
        )
    return replace(
        room,
        phase=phase,
        phase_deadline=deadline,
        match=None if phase is GamePhase.LOBBY else MatchState(),
    )


class ChatTests(unittest.TestCase):
    def dispatch(self, repository: FakeRepository, messages: list[dict[str, object]]) -> FakeSocket:
        socket = FakeSocket(
            [*(text_frame(message) for message in messages), DISCONNECT],
            service=FakeService(repository.stored.state),
        )
        socket.app.state.room_coordinator = RoomCoordinator(repository, socket.manager)
        run_socket(room_websocket(socket))
        return socket

    def test_message_is_trimmed_server_timestamped_and_serialized(self) -> None:
        room = make_room()
        command = SendChatMessage(
            request_id="chat-time", player_id="player-2", message="  hello room  "
        )
        outcome = apply_command(room, command, NOW)

        self.assertIsInstance(outcome, TransitionAccepted)
        record = outcome.state.chat_messages[0]
        self.assertEqual(record.message, "hello room")
        self.assertEqual(record.display_name, "Ben")
        self.assertEqual(record.sent_at, NOW)
        _, event = project_event(outcome.events[0], 1)
        self.assertEqual(event.payload["sent_at"], NOW.isoformat())
        recovered = deserialize_room(serialize_room(outcome.state))
        self.assertEqual(recovered.chat_messages, outcome.state.chat_messages)

    def test_chat_is_open_in_lobby_coding_and_discussion_only(self) -> None:
        allowed = (
            GamePhase.LOBBY,
            GamePhase.CODING_ROUND,
            GamePhase.MEETING_DISCUSSION,
        )
        for phase in allowed:
            with self.subTest(phase=phase):
                outcome = apply_command(
                    live_room_in_phase(phase),
                    SendChatMessage(
                        request_id=f"chat-{phase.value}",
                        player_id="player-2",
                        message="hello",
                    ),
                    NOW,
                )
                self.assertIsInstance(outcome, TransitionAccepted)

        closed = (
            GamePhase.CATEGORY_VOTE,
            GamePhase.ROLE_REVEAL,
            GamePhase.PLAYER_VOTE,
        )
        for phase in closed:
            with self.subTest(phase=phase):
                outcome = apply_command(
                    live_room_in_phase(phase),
                    SendChatMessage(
                        request_id=f"closed-{phase.value}",
                        player_id="player-2",
                        message="hello",
                    ),
                    NOW,
                )
                self.assertIsInstance(outcome, TransitionRejected)
                self.assertEqual(outcome.code, RejectionCode.WRONG_PHASE)

    def test_chat_closes_at_discussion_deadline_and_for_eliminated_players(self) -> None:
        discussion = live_room_in_phase(GamePhase.MEETING_DISCUSSION, due_at=NOW)
        late = apply_command(
            discussion,
            SendChatMessage(request_id="late-chat", player_id="player-2", message="late"),
            NOW,
        )
        self.assertIsInstance(late, TransitionRejected)
        self.assertEqual(late.code, RejectionCode.DEADLINE_PASSED)

        room = make_room()
        players = list(room.players)
        players[1] = replace(players[1], is_alive=False)
        eliminated = apply_command(
            replace(room, players=tuple(players)),
            SendChatMessage(request_id="dead-chat", player_id="player-2", message="hello"),
            NOW,
        )
        self.assertIsInstance(eliminated, TransitionRejected)
        self.assertEqual(eliminated.code, RejectionCode.PLAYER_NOT_CONNECTED)

    def test_history_keeps_only_the_latest_one_hundred_messages(self) -> None:
        state = make_room()
        for index in range(101):
            outcome = apply_command(
                state,
                SendChatMessage(
                    request_id=f"history-{index}",
                    player_id="player-2",
                    message=f"message {index}",
                ),
                NOW + timedelta(seconds=index),
            )
            self.assertIsInstance(outcome, TransitionAccepted)
            state = outcome.state

        self.assertEqual(len(state.chat_messages), 100)
        self.assertEqual(state.chat_messages[0].message, "message 1")
        self.assertEqual(state.chat_messages[-1].message, "message 100")

    def test_wire_rejects_blank_overlong_and_control_character_messages(self) -> None:
        repository = FakeRepository()
        socket = self.dispatch(repository, [
            wire_chat("blank", "   "),
            wire_chat("long", "x" * 501),
            wire_chat("control", "hello\nworld"),
        ])

        self.assertEqual([item["code"] for item in socket.sent[1:]], [
            "INVALID_MESSAGE", "INVALID_MESSAGE", "INVALID_MESSAGE",
        ])
        self.assertEqual(repository.stored.state.chat_messages, ())
        self.assertEqual(repository.stored.sequence, 1)  # Final socket loss is recorded.

    def test_sixth_message_in_ten_seconds_is_rejected(self) -> None:
        repository = FakeRepository()
        socket = self.dispatch(repository, [
            wire_chat(f"rate-{index}", f"message {index}") for index in range(6)
        ])

        chat_events = [item for item in socket.sent if item.get("name") == "ChatMessagePosted"]
        errors = [item for item in socket.sent if item.get("type") == "error"]
        self.assertEqual(len(chat_events), 5)
        self.assertEqual(len(repository.stored.state.chat_messages), 5)
        self.assertEqual(repository.stored.sequence, 6)
        self.assertEqual(errors[-1]["code"], RejectionCode.CHAT_RATE_LIMITED.value)

    def test_repeated_request_id_does_not_duplicate_chat_history(self) -> None:
        repository = FakeRepository()
        socket = self.dispatch(repository, [
            wire_chat("same-chat", "one message"),
            wire_chat("same-chat", "one message"),
        ])

        self.assertEqual(len(repository.stored.state.chat_messages), 1)
        self.assertEqual(repository.stored.sequence, 2)
        self.assertEqual(len(repository.receipts), 1)
        self.assertEqual([item["type"] for item in socket.sent], [
            "snapshot", "event", "ack", "ack",
        ])


if __name__ == "__main__":
    unittest.main()
