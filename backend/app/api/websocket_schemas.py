"""Version 1 WebSocket boundary models.

These are wire contracts, not game-engine commands or trusted domain events.
The gateway supplies player identity from the guest cookie; clients cannot put
``player_id`` in an accepted command envelope.
"""

from __future__ import annotations

import unicodedata
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, TypeAdapter, field_validator

from app.api.schemas import RoomSnapshot


PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 16 * 1024

RequestId = Annotated[
    str,
    StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"),
]
ShortToken = Annotated[
    str,
    StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$"),
]


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SetReadyAction(WireModel):
    name: Literal["set_ready"]
    ready: bool


class StartMatchAction(WireModel):
    name: Literal["start_match"]


class StartNextRoundAction(WireModel):
    name: Literal["start_next_round"]


class CastCategoryVoteAction(WireModel):
    name: Literal["cast_category_vote"]
    category_id: ShortToken


class CallEmergencyMeetingAction(WireModel):
    name: Literal["call_emergency_meeting"]


class CastPlayerVoteAction(WireModel):
    name: Literal["cast_player_vote"]
    target_player_id: ShortToken | None


class RequestOfficialTestRunAction(WireModel):
    name: Literal["request_official_test_run"]
    source_revision_id: ShortToken


class FinalizeSolutionAction(WireModel):
    name: Literal["finalize_solution"]
    source_revision_id: ShortToken


class SendChatMessageAction(WireModel):
    name: Literal["send_chat_message"]
    message: Annotated[str, StringConstraints(min_length=1, max_length=500)]

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > 500 or any(unicodedata.category(char) == "Cc" for char in value):
            raise ValueError("Chat message must be plain text between 1 and 500 characters.")
        return value


class LeaveRoomAction(WireModel):
    name: Literal["leave_room"]


class EndRoomAction(WireModel):
    name: Literal["end_room"]


class RequestRematchAction(WireModel):
    name: Literal["request_rematch"]


GameAction = Annotated[
    SetReadyAction
    | StartMatchAction
    | StartNextRoundAction
    | CastCategoryVoteAction
    | CallEmergencyMeetingAction
    | CastPlayerVoteAction
    | RequestOfficialTestRunAction
    | FinalizeSolutionAction
    | SendChatMessageAction
    | LeaveRoomAction
    | EndRoomAction
    | RequestRematchAction,
    Field(discriminator="name"),
]


class ClientCommand(WireModel):
    version: Literal[PROTOCOL_VERSION]
    type: Literal["command"]
    request_id: RequestId
    action: GameAction


class ClientPing(WireModel):
    version: Literal[PROTOCOL_VERSION]
    type: Literal["ping"]
    nonce: ShortToken


class ClientSnapshotRequest(WireModel):
    version: Literal[PROTOCOL_VERSION]
    type: Literal["snapshot_request"]
    request_id: RequestId


ClientMessage = Annotated[
    ClientCommand | ClientPing | ClientSnapshotRequest,
    Field(discriminator="type"),
]
client_message_adapter = TypeAdapter(ClientMessage)


class ServerSnapshot(WireModel):
    version: Literal[PROTOCOL_VERSION] = PROTOCOL_VERSION
    type: Literal["snapshot"] = "snapshot"
    sequence: int = Field(ge=0)
    request_id: RequestId | None = None
    room: RoomSnapshot


class ServerAcknowledgment(WireModel):
    version: Literal[PROTOCOL_VERSION] = PROTOCOL_VERSION
    type: Literal["ack"] = "ack"
    request_id: RequestId
    sequence: int = Field(ge=0)


class ServerEvent(WireModel):
    version: Literal[PROTOCOL_VERSION] = PROTOCOL_VERSION
    type: Literal["event"] = "event"
    sequence: int = Field(ge=1)
    name: ShortToken
    # Only the player-safe event projector may construct this payload.
    payload: dict[str, JsonValue]


class ServerError(WireModel):
    version: Literal[PROTOCOL_VERSION] = PROTOCOL_VERSION
    type: Literal["error"] = "error"
    code: ShortToken
    message: Annotated[str, StringConstraints(min_length=1, max_length=160)]
    request_id: RequestId | None = None


class ServerPong(WireModel):
    version: Literal[PROTOCOL_VERSION] = PROTOCOL_VERSION
    type: Literal["pong"] = "pong"
    nonce: ShortToken
