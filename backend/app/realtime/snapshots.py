"""Allowlisted public/private projections of trusted game data."""

from __future__ import annotations

from app.api.schemas import build_room_response
from app.api.websocket_schemas import ServerEvent, ServerSnapshot
from app.game import events as domain
from app.game.models import RoomState


def room_snapshot(state: RoomState, player_id: str, sequence: int, request_id: str | None = None) -> ServerSnapshot:
    return ServerSnapshot(
        sequence=sequence,
        request_id=request_id,
        room=build_room_response(state, player_id).room,
    )


def project_event(event: domain.GameEvent, sequence: int) -> tuple[str | None, ServerEvent]:
    """Return (recipient, envelope); None means a public room event.

    Every event type must be listed here. Unknown types fail closed rather than
    serializing a new domain field that could contain private information.
    """

    recipient: str | None = None
    if isinstance(event, domain.PlayerRoleAssigned):
        recipient = event.recipient_player_id
        payload = {"role": event.role.value}
    elif isinstance(event, domain.PlayerBallotStored):
        recipient = event.recipient_player_id
        payload = {"is_skip": event.is_skip}
    elif isinstance(event, domain.SabotageObjectiveVerified):
        recipient = event.recipient_player_id
        payload = {"objective_id": event.objective_id, "source_revision_id": event.source_revision_id}
    elif isinstance(event, domain.PlayerReadinessChanged):
        payload = {"player_id": event.player_id, "is_ready": event.is_ready}
    elif isinstance(event, domain.MatchStarted):
        payload = {}
    elif isinstance(event, domain.CategoryVoteRecorded):
        # Individual category ballots stay private until resolution.
        recipient = event.player_id
        payload = {"recorded": True}
    elif isinstance(event, domain.CategorySelected):
        payload = {"category_id": event.category_id, "vote_counts": dict(event.vote_counts), "used_fallback": event.used_fallback}
    elif isinstance(event, domain.CodingRoundStarted):
        payload = {"round_number": event.round_number, "category_id": event.category_id,
                   "challenge_id": event.challenge_id, "challenge_version": event.challenge_version,
                   "deadline_at": event.deadline_at.isoformat()}
    elif isinstance(event, domain.MeetingStarted):
        payload = {"caller_player_id": event.caller_player_id, "discussion_deadline_at": event.discussion_deadline_at.isoformat()}
    elif isinstance(event, domain.PlayerVotingStarted):
        payload = {"deadline_at": event.deadline_at.isoformat()}
    elif isinstance(event, domain.PlayerVoteResolved):
        payload = {"vote_counts": dict(event.vote_counts), "skip_count": event.skip_count,
                   "ejected_player_id": event.ejected_player_id, "was_tie": event.was_tie}
    elif isinstance(event, domain.PlayerEliminated):
        payload = {"player_id": event.player_id}
    elif isinstance(event, domain.OfficialTestRunRequested):
        recipient = event.player_id
        payload = {"source_revision_id": event.source_revision_id}
    elif isinstance(event, domain.OfficialTestResultAccepted):
        payload = {"source_revision_id": event.source_revision_id, "all_required_tests_passed": event.all_required_tests_passed}
    elif isinstance(event, domain.SourceRevisionChanged):
        payload = {"source_revision_id": event.source_revision_id}
    elif isinstance(event, domain.RoundEnded):
        payload = {"round_number": event.round_number}
    elif isinstance(event, domain.MatchEnded):
        payload = {"winner": event.winner.value, "reason": event.reason.value, "round_number": event.round_number}
    elif isinstance(event, domain.ChatMessagePosted):
        payload = {"player_id": event.player_id, "message": event.message}
    elif isinstance(event, (domain.PlayerDeparted, domain.PlayerDisconnected, domain.PlayerReconnected)):
        payload = {"player_id": event.player_id}
    elif isinstance(event, domain.HostTransferred):
        payload = {"previous_host_player_id": event.previous_host_player_id,
                   "new_host_player_id": event.new_host_player_id}
    elif isinstance(event, domain.RoomClosed):
        payload = {}
    elif isinstance(event, domain.RematchRequested):
        payload = {"player_id": event.player_id}
    elif isinstance(event, domain.RematchStarted):
        payload = {}
    else:
        raise ValueError(f"No safe projection for {type(event).__name__}")
    if isinstance(event, domain.PrivateGameEvent) and recipient is None:
        raise ValueError("Private game event has no recipient.")
    return recipient, ServerEvent(sequence=sequence, name=type(event).__name__, payload=payload)
