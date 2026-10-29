"""Authorized, player-safe editor sessions and trusted sync-service commits."""

from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone
import hmac
import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.rooms import COOKIE_NAME, _require_allowed_origin
from app.challenges.loader import ChallengeLoadError, load_challenge
from app.game.models import ConnectionStatus, GamePhase
from app.rooms.repository import (
    EditorStorageLimitError, MAX_EDITOR_SOURCE_BYTES, MAX_EDITOR_Y_STATE_BYTES,
    RoomStorageError, editor_document_id,
)
from app.rooms.service import RoomServiceError


router = APIRouter(prefix="/api/rooms/editor", tags=["editor"])


class EditorModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SessionRequest(EditorModel):
    room_code: str = Field(min_length=1, max_length=32)
    round_number: int = Field(ge=1, le=4)


class DocumentRequest(EditorModel):
    document_id: str = Field(min_length=1, max_length=180)


class CommitRequest(DocumentRequest):
    previous_revision_id: str = Field(min_length=1, max_length=80)
    source: str = Field(max_length=65_536)
    y_state: str = Field(min_length=1, max_length=400_000)
    restored_from_revision_id: str | None = Field(default=None, min_length=1, max_length=80)


class InitializeRequest(DocumentRequest):
    y_state: str = Field(min_length=1, max_length=400_000)


def _error(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status,
                        headers={"Cache-Control": "no-store"})


def _service_authorized(request: Request) -> bool:
    configured = request.app.state.editor_service_key
    provided = request.headers.get("x-editor-service-key", "")
    return bool(configured and provided and hmac.compare_digest(configured, provided))


async def _guest(request: Request):
    return await request.app.state.room_service.authenticate_player(request.cookies.get(COOKIE_NAME))


def _round_for(state, player_id: str, document_id: str | None = None):
    match = state.match
    current = match.current_round if match else None
    player = next((item for item in state.players if item.player_id == player_id), None)
    if (state.phase is not GamePhase.CODING_ROUND or match is None or current is None
        or match.match_id is None or player is None
        or player.connection is ConnectionStatus.DEPARTED or not player.is_alive
        or datetime.now(timezone.utc) >= current.deadline.due_at):
        return None
    expected = editor_document_id(state)
    if document_id is not None and document_id != expected:
        return None
    return current, expected


def _history_payload(document):
    return [{"revision_id": item.revision_id, "source": item.source,
             "author_player_id": item.author_player_id,
             "recorded_at": item.recorded_at.isoformat(),
             "restored_from_revision_id": item.restored_from_revision_id}
            for item in document.history] if document else []


@router.post("/session")
async def editor_session(payload: SessionRequest, request: Request):
    try:
        _require_allowed_origin(request)
        guest = await _guest(request)
        if guest.state.room_code != payload.room_code:
            return _error("EDITOR_FORBIDDEN", "This editor is outside your room.", 403)
        selected = _round_for(guest.state, guest.player_id)
        if selected is None or selected[0].number != payload.round_number:
            return _error("EDITOR_UNAVAILABLE", "The requested coding round is not open.", 409)
        if not request.app.state.editor_service_key:
            return _error("EDITOR_UNAVAILABLE", "The editor service is not configured.", 503)
        current, document_id = selected
        loaded = load_challenge(current.challenge_id, current.challenge_version)
        if loaded.content_digest != current.challenge_content_digest:
            return _error("CHALLENGE_CHANGED", "The pinned challenge has changed.", 409)
        challenge = loaded.challenge
        return JSONResponse({
            "room_code": payload.room_code, "round_number": current.number,
            "document_id": document_id,
            "websocket_url": request.app.state.editor_websocket_url,
            "challenge": {"id": challenge.id, "version": challenge.version,
                          "category": challenge.category, "title": challenge.title,
                          "prompt": challenge.prompt, "language": challenge.language,
                          "starter_code": challenge.starter_code},
        }, headers={"Cache-Control": "no-store"})
    except RoomServiceError as exc:
        return _error(exc.code, exc.message, exc.status_code)
    except RoomStorageError:
        return _error("STORAGE_UNAVAILABLE", "Editor storage is unavailable.", 503)
    except ChallengeLoadError:
        return _error("CHALLENGE_UNAVAILABLE", "The pinned challenge is unavailable.", 503)


@router.post("/history")
async def editor_history(payload: DocumentRequest, request: Request):
    try:
        _require_allowed_origin(request)
        guest = await _guest(request)
        if _round_for(guest.state, guest.player_id, payload.document_id) is None:
            return _error("EDITOR_FORBIDDEN", "This document is not your current round.", 403)
        document = await request.app.state.room_repository.load_editor_document(payload.document_id)
        current, _ = _round_for(guest.state, guest.player_id, payload.document_id)
        if document is None and not current.current_source_revision_id.startswith("seed-"):
            return _error("REVISION_CONFLICT", "The saved editor document is missing.", 409)
        if document is not None and document.revision_id != current.current_source_revision_id:
            return _error("REVISION_CONFLICT", "Editor storage and room revision disagree.", 409)
        return JSONResponse({"revision_id": document.revision_id if document else None,
                             "history": _history_payload(document)},
                            headers={"Cache-Control": "no-store"})
    except RoomServiceError as exc:
        return _error(exc.code, exc.message, exc.status_code)
    except RoomStorageError:
        return _error("STORAGE_UNAVAILABLE", "Editor storage is unavailable.", 503)


@router.post("/internal/authorize")
async def authorize_editor(payload: DocumentRequest, request: Request):
    if not _service_authorized(request):
        return _error("EDITOR_FORBIDDEN", "Editor service is not authorized.", 403)
    try:
        guest = await _guest(request)
        selected = _round_for(guest.state, guest.player_id, payload.document_id)
        if selected is None:
            return _error("EDITOR_FORBIDDEN", "This document is not your current round.", 403)
        current, _ = selected
        document = await request.app.state.room_repository.load_editor_document(payload.document_id)
        if document is None and not current.current_source_revision_id.startswith("seed-"):
            return _error("REVISION_CONFLICT", "The saved editor document is missing.", 409)
        if document is not None and document.revision_id != current.current_source_revision_id:
            return _error("REVISION_CONFLICT", "Editor storage and room revision disagree.", 409)
        loaded = load_challenge(current.challenge_id, current.challenge_version)
        if loaded.content_digest != current.challenge_content_digest:
            return _error("CHALLENGE_CHANGED", "The pinned challenge has changed.", 409)
        return JSONResponse({
            "player_id": guest.player_id,
            "display_name": next(player.display_name for player in guest.state.players
                                 if player.player_id == guest.player_id),
            "revision_id": current.current_source_revision_id,
            "source": document.source if document else loaded.challenge.starter_code,
            "y_state": document.y_state if document else None,
            "history": _history_payload(document),
        }, headers={"Cache-Control": "no-store"})
    except RoomServiceError as exc:
        return _error(exc.code, exc.message, exc.status_code)
    except RoomStorageError:
        return _error("STORAGE_UNAVAILABLE", "Editor storage is unavailable.", 503)
    except ChallengeLoadError:
        return _error("CHALLENGE_UNAVAILABLE", "The pinned challenge is unavailable.", 503)


@router.post("/internal/commit")
async def commit_editor(payload: CommitRequest, request: Request):
    if not _service_authorized(request):
        return _error("EDITOR_FORBIDDEN", "Editor service is not authorized.", 403)
    try:
        if (len(base64.b64decode(payload.y_state, validate=True)) > MAX_EDITOR_Y_STATE_BYTES
            or len(payload.source.encode("utf-8")) > MAX_EDITOR_SOURCE_BYTES):
            return _error("EDITOR_TOO_LARGE", "Editor document is too large.", 413)
    except (ValueError, binascii.Error):
        return _error("INVALID_DOCUMENT", "Editor document encoding is invalid.", 422)
    try:
        guest = await _guest(request)
        if _round_for(guest.state, guest.player_id, payload.document_id) is None:
            return _error("EDITOR_FORBIDDEN", "This document is not your current round.", 403)
        revision_id = await request.app.state.room_coordinator.commit_editor_change(
            guest.state.room_code, guest.player_id, payload.document_id,
            payload.previous_revision_id, payload.source, payload.y_state,
            payload.restored_from_revision_id,
        )
        if revision_id is None:
            return _error("REVISION_CONFLICT", "The coding round or source revision changed.", 409)
        return JSONResponse({"revision_id": revision_id}, headers={"Cache-Control": "no-store"})
    except RoomServiceError as exc:
        return _error(exc.code, exc.message, exc.status_code)
    except EditorStorageLimitError:
        return _error("EDITOR_TOO_LARGE", "Editor document is too large.", 413)
    except RoomStorageError:
        return _error("STORAGE_UNAVAILABLE", "Editor storage is unavailable.", 503)


@router.post("/internal/initialize")
async def initialize_editor(payload: InitializeRequest, request: Request):
    if not _service_authorized(request):
        return _error("EDITOR_FORBIDDEN", "Editor service is not authorized.", 403)
    try:
        if len(base64.b64decode(payload.y_state, validate=True)) > MAX_EDITOR_Y_STATE_BYTES:
            return _error("EDITOR_TOO_LARGE", "Editor document is too large.", 413)
    except (ValueError, binascii.Error):
        return _error("INVALID_DOCUMENT", "Editor document encoding is invalid.", 422)
    try:
        guest = await _guest(request)
        selected = _round_for(guest.state, guest.player_id, payload.document_id)
        if selected is None:
            return _error("EDITOR_FORBIDDEN", "This document is not your current round.", 403)
        current, _ = selected
        stored = await request.app.state.room_repository.load_room(guest.state.room_code)
        loaded = load_challenge(current.challenge_id, current.challenge_version)
        if stored is None or stored.state != guest.state or loaded.content_digest != current.challenge_content_digest:
            return _error("REVISION_CONFLICT", "The round changed while opening the editor.", 409)
        if not await request.app.state.room_repository.initialize_editor_document(
            stored, document_id=payload.document_id,
            source=loaded.challenge.starter_code, y_state=payload.y_state,
        ):
            return _error("REVISION_CONFLICT", "The editor was initialized elsewhere.", 409)
        return JSONResponse({"revision_id": current.current_source_revision_id},
                            headers={"Cache-Control": "no-store"})
    except RoomServiceError as exc:
        return _error(exc.code, exc.message, exc.status_code)
    except EditorStorageLimitError:
        return _error("EDITOR_TOO_LARGE", "Editor document is too large.", 413)
    except RoomStorageError:
        return _error("STORAGE_UNAVAILABLE", "Editor storage is unavailable.", 503)
    except ChallengeLoadError:
        return _error("CHALLENGE_UNAVAILABLE", "The pinned challenge is unavailable.", 503)
