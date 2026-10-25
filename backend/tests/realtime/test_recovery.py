"""Durable player grace and abandoned official-run recovery."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest

from app.game.models import (
    ConnectionStatus, DeadlineKind, GameDeadline, GamePhase, MatchState,
    OfficialRunProgress, OfficialRunStatus, RoundState,
)
from app.game.commands import SendChatMessage
from app.game.transitions import apply_command
from app.game.outcomes import TransitionAccepted
from app.api.websocket_schemas import ServerEvent
from app.realtime.connection_manager import RoomConnectionManager
from app.realtime.coordinator import RoomCoordinator
from app.realtime.deadline_scheduler import DeadlineAttempt
from app.rooms.identity import credential_digest
from app.rooms.redis_repository import _indexed_deadlines
from app.rooms.repository import GuestSession, RoomStorageError
from app.rooms.service import RoomService, RoomServiceError
from _support import FakeRepository, FakeSocket, make_room, run_socket


class RecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rooms = FakeRepository()
        self.connections = RoomConnectionManager()
        self.coordinator = RoomCoordinator(self.rooms, self.connections)
        self.code = self.rooms.stored.state.room_code

    def test_only_the_last_tab_starts_reconnect_grace(self) -> None:
        other_tab = self.connections.register(self.code, "player-2", FakeSocket([]))
        run_socket(self.coordinator.mark_disconnected(self.code, "player-2"))
        self.assertEqual(self.rooms.stored.state.players[1].connection, ConnectionStatus.CONNECTED)

        self.connections.unregister(other_tab)
        run_socket(self.coordinator.mark_disconnected(self.code, "player-2"))
        player = self.rooms.stored.state.players[1]
        self.assertEqual(player.connection, ConnectionStatus.DISCONNECTED)
        self.assertEqual(player.reconnect_deadline.kind, DeadlineKind.RECONNECT_GRACE)

    def test_storage_outage_during_delivery_does_not_depart_a_live_socket(self) -> None:
        async def unavailable(_credential):
            raise RoomStorageError("Redis is unavailable.")

        manager = RoomConnectionManager(unavailable)
        socket = FakeSocket([])
        manager.register(self.code, "player-2", socket, "credential")
        run_socket(manager.broadcast(self.code, ServerEvent(
            sequence=1, name="RoomChanged", payload={},
        )))
        self.assertTrue(manager.has_connections(self.code, "player-2"))
        self.assertEqual(socket.sent, [])

    def test_return_clears_grace_and_old_callback_is_stale(self) -> None:
        run_socket(self.coordinator.mark_disconnected(self.code, "player-2"))
        old_deadline = self.rooms.stored.state.players[1].reconnect_deadline
        outcomes = []

        async def restore_and_replay() -> None:
            outcomes.append(await self.coordinator.restore_connection(self.code, "player-2"))
            outcomes.append(await self.coordinator.resolve_game_deadline(
                self.code, old_deadline.deadline_id,
            ))

        run_socket(restore_and_replay())
        self.assertEqual(outcomes, [True, DeadlineAttempt.STALE])
        player = self.rooms.stored.state.players[1]
        self.assertEqual(player.connection, ConnectionStatus.CONNECTED)
        self.assertIsNone(player.reconnect_deadline)

    def test_expired_grace_departs_once_and_rejects_late_return(self) -> None:
        now = datetime.now(timezone.utc)
        deadline = GameDeadline("expired-grace", DeadlineKind.RECONNECT_GRACE,
                                now - timedelta(seconds=1))
        players = list(self.rooms.stored.state.players)
        players[1] = replace(players[1], connection=ConnectionStatus.DISCONNECTED,
                             reconnect_deadline=deadline)
        self.rooms.stored = replace(self.rooms.stored,
            state=replace(self.rooms.stored.state, players=tuple(players)))
        outcomes = []

        async def expire_twice() -> None:
            outcomes.append(await self.coordinator.resolve_game_deadline(
                self.code, deadline.deadline_id,
            ))
            outcomes.append(await self.coordinator.resolve_game_deadline(
                self.code, deadline.deadline_id,
            ))
            outcomes.append(await self.coordinator.restore_connection(self.code, "player-2"))

        run_socket(expire_twice())
        self.assertEqual(outcomes, [DeadlineAttempt.COMMITTED, DeadlineAttempt.STALE, False])
        self.assertEqual(self.rooms.stored.state.players[1].connection, ConnectionStatus.DEPARTED)

    def test_host_loss_transfers_host_after_grace(self) -> None:
        now = datetime.now(timezone.utc)
        deadline = GameDeadline("host-grace", DeadlineKind.RECONNECT_GRACE,
                                now - timedelta(seconds=1))
        players = list(self.rooms.stored.state.players)
        players[0] = replace(players[0], connection=ConnectionStatus.DISCONNECTED,
                             reconnect_deadline=deadline)
        self.rooms.stored = replace(self.rooms.stored,
            state=replace(self.rooms.stored.state, players=tuple(players)))
        outcomes = []

        async def expire_host() -> None:
            outcomes.append(await self.coordinator.resolve_game_deadline(
                self.code, deadline.deadline_id,
            ))

        run_socket(expire_host())
        self.assertEqual(outcomes, [DeadlineAttempt.COMMITTED])
        self.assertEqual(self.rooms.stored.state.host_player_id, "player-2")
        self.assertEqual(self.rooms.stored.state.players[0].connection, ConnectionStatus.DEPARTED)

    def test_startup_reconciles_players_from_the_previous_process(self) -> None:
        run_socket(self.coordinator.recover_orphaned_connections())
        self.assertTrue(all(player.connection is ConnectionStatus.DISCONNECTED
                            for player in self.rooms.stored.state.players))
        self.assertTrue(all(player.reconnect_deadline is not None
                            for player in self.rooms.stored.state.players))

    def test_grace_and_phase_deadlines_are_both_indexed(self) -> None:
        now = datetime.now(timezone.utc)
        phase_deadline = GameDeadline("coding-1", DeadlineKind.CODING_ROUND,
                                      now + timedelta(minutes=2))
        reconnect_deadline = GameDeadline("reconnect-1", DeadlineKind.RECONNECT_GRACE,
                                          now + timedelta(seconds=30))
        players = list(self.rooms.stored.state.players)
        players[1] = replace(players[1], connection=ConnectionStatus.DISCONNECTED,
                             reconnect_deadline=reconnect_deadline)
        state = replace(self.rooms.stored.state, players=tuple(players),
                        phase=GamePhase.CODING_ROUND, phase_deadline=phase_deadline,
                        match=MatchState())
        indexed = dict(_indexed_deadlines(state))
        self.assertEqual(indexed[f"{self.code}:coding-1"], phase_deadline.due_at.timestamp())
        self.assertEqual(indexed[f"{self.code}:reconnect-1"], reconnect_deadline.due_at.timestamp())

    def test_http_resume_rotates_credential_and_restores_same_player(self) -> None:
        now = datetime.now(timezone.utc)
        credential = "A" * 43
        deadline = GameDeadline("reconnect-http", DeadlineKind.RECONNECT_GRACE,
                                now + timedelta(seconds=30))
        players = list(self.rooms.stored.state.players)
        players[1] = replace(players[1], connection=ConnectionStatus.DISCONNECTED,
                             reconnect_deadline=deadline)
        self.rooms.stored = replace(self.rooms.stored,
            state=replace(self.rooms.stored.state, players=tuple(players)))
        old_hash = credential_digest(credential)
        self.rooms.sessions[old_hash] = GuestSession(
            old_hash, self.code, "player-2", now + timedelta(minutes=5),
        )
        service = RoomService(self.rooms, clock=lambda: now)
        results = []

        async def resume() -> None:
            results.append(await service.resume_player(credential))

        run_socket(resume())
        self.assertEqual(results[0].player_id, "player-2")
        self.assertNotEqual(results[0].credential, credential)
        self.assertNotIn(old_hash, self.rooms.sessions)
        self.assertEqual(self.rooms.stored.state.players[1].connection, ConnectionStatus.CONNECTED)

    def test_http_auth_rejects_return_after_grace(self) -> None:
        now = datetime.now(timezone.utc)
        credential = "B" * 43
        deadline = GameDeadline("reconnect-expired", DeadlineKind.RECONNECT_GRACE,
                                now - timedelta(seconds=1))
        players = list(self.rooms.stored.state.players)
        players[1] = replace(players[1], connection=ConnectionStatus.DISCONNECTED,
                             reconnect_deadline=deadline)
        self.rooms.stored = replace(self.rooms.stored,
            state=replace(self.rooms.stored.state, players=tuple(players)))
        old_hash = credential_digest(credential)
        self.rooms.sessions[old_hash] = GuestSession(
            old_hash, self.code, "player-2", now + timedelta(minutes=5),
        )
        service = RoomService(self.rooms, clock=lambda: now)
        failures = []

        async def authenticate() -> None:
            try:
                await service.authenticate_player(credential)
            except RoomServiceError as exc:
                failures.append(exc.code)

        run_socket(authenticate())
        self.assertEqual(failures, ["RECONNECT_GRACE_EXPIRED"])

        departed = list(self.rooms.stored.state.players)
        departed[1] = replace(departed[1], connection=ConnectionStatus.DEPARTED,
                              reconnect_deadline=None, is_ready=False, is_alive=False)
        self.rooms.stored = replace(self.rooms.stored,
            state=replace(self.rooms.stored.state, players=tuple(departed)))
        run_socket(authenticate())
        self.assertEqual(failures, ["RECONNECT_GRACE_EXPIRED", "RECONNECT_GRACE_EXPIRED"])

    def test_join_keeps_existing_lobby_chat_history(self) -> None:
        now = datetime.now(timezone.utc)
        chat = apply_command(self.rooms.stored.state, SendChatMessage(
            request_id="lobby-chat", player_id="player-1", message="Welcome",
        ), now)
        self.assertIsInstance(chat, TransitionAccepted)
        self.rooms.stored = replace(self.rooms.stored, state=chat.state)
        service = RoomService(self.rooms, clock=lambda: now)
        results = []

        async def join() -> None:
            results.append(await service.join_room(self.code, "Cia", join_subject="test"))

        run_socket(join())
        self.assertEqual(results[0].state.chat_messages, chat.state.chat_messages)
        self.assertEqual(len(self.rooms.stored.state.players), 3)

    def test_timed_out_run_becomes_error_once(self) -> None:
        now = datetime.now(timezone.utc)
        run = OfficialRunProgress(
            run_id="a" * 32, source_revision_id="revision-1",
            requested_by_player_id="player-2", requested_at=now - timedelta(seconds=60),
            updated_at=now - timedelta(seconds=60), status=OfficialRunStatus.QUEUED,
        )
        deadline = GameDeadline("coding-1", DeadlineKind.CODING_ROUND,
                                now + timedelta(minutes=2))
        current_round = RoundState(
            number=1, category_id="object-oriented", challenge_id="oop.counter",
            challenge_version="1.0.0", challenge_content_digest="sha256:fixture",
            started_at=now - timedelta(minutes=2), deadline=deadline,
            current_source_revision_id="revision-1", official_run_progress=(run,),
        )
        state = replace(self.rooms.stored.state, phase=GamePhase.CODING_ROUND,
                        phase_deadline=deadline,
                        match=MatchState(round_number=1, selected_category_id="object-oriented",
                                         current_round=current_round))
        self.rooms.stored = replace(self.rooms.stored, state=state)
        outcomes = []

        async def expire_twice() -> None:
            outcomes.append(await self.coordinator.expire_stale_official_runs(
                self.code, timeout_seconds=45,
            ))
            outcomes.append(await self.coordinator.expire_stale_official_runs(
                self.code, timeout_seconds=45,
            ))

        run_socket(expire_twice())
        self.assertEqual(outcomes, [1, 0])
        progress = self.rooms.stored.state.match.current_round.official_run_progress[0]
        self.assertEqual(progress.status, OfficialRunStatus.ERROR)
        self.assertEqual(self.rooms.stored.state.phase, GamePhase.CODING_ROUND)


if __name__ == "__main__":
    unittest.main()
