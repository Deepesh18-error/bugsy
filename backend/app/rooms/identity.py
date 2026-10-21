"""Opaque guest identities, room codes, and display-name normalization."""

from __future__ import annotations

import hashlib
import re
import secrets
import unicodedata


ROOM_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
ROOM_CODE_LENGTH = 8
_ROOM_CODE_PATTERN = re.compile(r"^[A-HJ-NP-Z2-9]{8}$")


def normalize_display_name(value: str) -> str:
    """Use one visible, comparable form without accepting control characters."""

    if not isinstance(value, str):
        raise ValueError("Display name must be text.")
    normalized = unicodedata.normalize("NFKC", value)
    if any(unicodedata.category(character).startswith("C") for character in normalized):
        raise ValueError("Display name cannot contain control or invisible characters.")
    normalized = " ".join(normalized.split())
    if not 2 <= len(normalized) <= 24:
        raise ValueError("Display name must contain 2 to 24 characters.")
    return normalized


def display_name_key(value: str) -> str:
    """Case-insensitive key for checking duplicate names inside one room."""

    return normalize_display_name(value).casefold()


def normalize_room_code(value: str) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().upper()
    return normalized if _ROOM_CODE_PATTERN.fullmatch(normalized) else None


def new_room_code() -> str:
    return "".join(secrets.choice(ROOM_CODE_ALPHABET) for _ in range(ROOM_CODE_LENGTH))


def new_player_id() -> str:
    return secrets.token_urlsafe(18)


def new_reconnect_credential() -> str:
    return secrets.token_urlsafe(32)


def credential_digest(credential: str) -> str:
    """SHA-256 is suitable here because the input is a random 256-bit secret."""

    if not isinstance(credential, str) or not credential:
        raise ValueError("A reconnect credential is required.")
    return hashlib.sha256(credential.encode("utf-8")).hexdigest()
