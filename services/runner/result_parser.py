"""Strict, bounded parser for replies from a submitted-code jail.

The jail can control stdout. Every message is treated as untrusted input;
official verdict documents are built only by the supervisor's trusted tests.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json


MAX_LINE_BYTES = 4_096


class SandboxProtocolError(ValueError):
    """The jailed process sent an oversized, forged, or malformed message."""


@dataclass(frozen=True, slots=True)
class OperationReply:
    ok: bool
    value: object | None = None
    error_kind: str | None = None


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SandboxProtocolError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_: str) -> object:
    raise SandboxProtocolError("nonfinite JSON value")


async def read_document(reader: asyncio.StreamReader) -> dict[str, object]:
    try:
        line = await reader.readline()
    except (ValueError, asyncio.LimitOverrunError) as exc:
        raise SandboxProtocolError("sandbox output line exceeds its limit") from exc
    if not line or len(line) > MAX_LINE_BYTES or not line.endswith(b"\n"):
        raise SandboxProtocolError("sandbox output is missing or too large")
    try:
        value = json.loads(line.decode("utf-8"), object_pairs_hook=_unique_object,
                           parse_constant=_reject_constant)
    except (UnicodeError, json.JSONDecodeError, TypeError) as exc:
        raise SandboxProtocolError("sandbox output is not valid JSON") from exc
    if not isinstance(value, dict):
        raise SandboxProtocolError("sandbox output must be an object")
    return value


def parse_ready(document: dict[str, object]) -> None:
    if document != {"type": "ready", "protocol_version": 1}:
        raise SandboxProtocolError("sandbox did not complete its handshake")


def parse_reply(document: dict[str, object], nonce: str) -> OperationReply:
    if document.get("nonce") != nonce or type(document.get("ok")) is not bool:
        raise SandboxProtocolError("sandbox reply does not match the request")
    if document["ok"]:
        if set(document) != {"nonce", "ok", "value"}:
            raise SandboxProtocolError("successful sandbox reply has unexpected fields")
        return OperationReply(ok=True, value=document["value"])
    if set(document) != {"nonce", "ok", "error_kind"} or document["error_kind"] != "exception":
        raise SandboxProtocolError("failed sandbox reply has unexpected fields")
    return OperationReply(ok=False, error_kind="exception")
