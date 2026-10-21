"""HTTP entry points for temporary guest rooms and cookie-based resume."""

from __future__ import annotations

import math
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from app.api.schemas import (
    ApiError,
    CreateRoomRequest,
    ErrorResponse,
    JoinRoomRequest,
    RoomResponse,
    build_room_response,
)
from app.rooms.repository import RoomStorageError
from app.rooms.service import GuestResult, RoomService, RoomServiceError


router = APIRouter(prefix="/api/rooms", tags=["rooms"])
COOKIE_NAME = "codemafia_guest"
COOKIE_PATH = "/api/rooms"
ERROR_RESPONSES = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    429: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
}


def _service(request: Request) -> RoomService:
    return request.app.state.room_service


def _require_allowed_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin is not None and origin not in request.app.state.allowed_origins:
        raise RoomServiceError("ORIGIN_FORBIDDEN", "Origin is not allowed.", 403)


def _error(exc: RoomServiceError | RoomStorageError) -> JSONResponse:
    if isinstance(exc, RoomStorageError):
        exc = RoomServiceError("STORAGE_UNAVAILABLE", "Room service is unavailable.", 503)
    content = ErrorResponse(error=ApiError(code=exc.code, message=exc.message))
    return JSONResponse(
        status_code=exc.status_code,
        content=content.model_dump(mode="json"),
        headers={"Cache-Control": "no-store"},
    )


def _success(response: Response, result: GuestResult, request: Request) -> RoomResponse:
    remaining = math.ceil(
        (result.credential_expires_at - datetime.now(timezone.utc)).total_seconds()
    )
    response.set_cookie(
        key=COOKIE_NAME,
        value=result.credential,
        max_age=max(1, remaining),
        httponly=True,
        secure=request.app.state.secure_guest_cookie,
        samesite=request.app.state.guest_cookie_samesite,
        path=COOKIE_PATH,
    )
    response.headers["Cache-Control"] = "no-store"
    return build_room_response(result.state, result.player_id)


@router.post("", response_model=RoomResponse, status_code=201, responses=ERROR_RESPONSES)
async def create_room(
    payload: CreateRoomRequest, request: Request, response: Response
) -> RoomResponse | JSONResponse:
    try:
        _require_allowed_origin(request)
        result = await _service(request).create_room(payload.display_name, payload.capacity)
        return _success(response, result, request)
    except (RoomServiceError, RoomStorageError) as exc:
        return _error(exc)


@router.post("/join", response_model=RoomResponse, responses=ERROR_RESPONSES)
async def join_room(
    payload: JoinRoomRequest, request: Request, response: Response
) -> RoomResponse | JSONResponse:
    try:
        _require_allowed_origin(request)
        subject = request.client.host if request.client is not None else "unknown"
        result = await _service(request).join_room(
            payload.room_code, payload.display_name, join_subject=subject
        )
        return _success(response, result, request)
    except (RoomServiceError, RoomStorageError) as exc:
        return _error(exc)


@router.post("/resume", response_model=RoomResponse, responses=ERROR_RESPONSES)
async def resume_player(request: Request, response: Response) -> RoomResponse | JSONResponse:
    try:
        _require_allowed_origin(request)
        result = await _service(request).resume_player(request.cookies.get(COOKIE_NAME))
        return _success(response, result, request)
    except (RoomServiceError, RoomStorageError) as exc:
        return _error(exc)


@router.post("/leave", status_code=204, responses=ERROR_RESPONSES)
async def leave_room(request: Request, response: Response) -> Response:
    try:
        _require_allowed_origin(request)
        await _service(request).leave_room(request.cookies.get(COOKIE_NAME))
        response.status_code = 204
        response.delete_cookie(
            key=COOKIE_NAME,
            path=COOKIE_PATH,
            secure=request.app.state.secure_guest_cookie,
            httponly=True,
            samesite=request.app.state.guest_cookie_samesite,
        )
        response.headers["Cache-Control"] = "no-store"
        return response
    except (RoomServiceError, RoomStorageError) as exc:
        return _error(exc)
