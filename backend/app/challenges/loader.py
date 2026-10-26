"""Deterministic loading and integrity hashing for the authored challenge bank."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from .schema import Challenge, ContentId, SemanticVersion


_CONTENT_DIRECTORY = Path(__file__).resolve().parent / "content"
_CONTENT_ID_ADAPTER = TypeAdapter(ContentId)
_VERSION_ADAPTER = TypeAdapter(SemanticVersion)


class ChallengeLoadError(ValueError):
    """Raised when the challenge bank cannot provide a valid requested version."""


@dataclass(frozen=True, slots=True)
class LoadedChallenge:
    """A validated challenge plus a digest of its canonical content."""

    challenge: Challenge
    content_digest: str


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject ambiguous JSON objects instead of silently keeping the last key."""

    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _canonical_digest(challenge: Challenge) -> str:
    """Hash validated content independent of JSON whitespace and key order."""

    canonical_json = json.dumps(
        challenge.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _read_challenge_file(path: Path) -> Challenge:
    """Read and validate one trusted JSON challenge document."""

    try:
        raw_content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ChallengeLoadError(f"Cannot read challenge file '{path.name}'.") from exc

    try:
        payload = json.loads(
            raw_content,
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise ChallengeLoadError(
            f"Challenge file '{path.name}' is not valid unambiguous JSON: {exc}"
        ) from exc

    if not isinstance(payload, dict):
        raise ChallengeLoadError(
            f"Challenge file '{path.name}' must contain a JSON object at its root."
        )

    try:
        return Challenge.model_validate(payload)
    except ValidationError as exc:
        raise ChallengeLoadError(
            f"Challenge file '{path.name}' does not match the challenge schema: {exc}"
        ) from exc


def load_challenge(challenge_id: str, version: str) -> LoadedChallenge:
    """Load exactly one challenge version from the trusted content directory.

    Every JSON file in the small authored bank is parsed and validated so a
    malformed file or duplicate (ID, version) cannot be hidden by filesystem
    ordering. The ID and version inside each document are authoritative; file
    names are for people and do not determine which version is returned.
    """

    try:
        normalized_id = _CONTENT_ID_ADAPTER.validate_python(challenge_id)
        normalized_version = _VERSION_ADAPTER.validate_python(version)
    except ValidationError as exc:
        raise ChallengeLoadError("The requested challenge ID or version is invalid.") from exc

    if not _CONTENT_DIRECTORY.is_dir():
        raise ChallengeLoadError("The challenge content directory does not exist.")

    content_files = sorted(_CONTENT_DIRECTORY.glob("*.json"), key=lambda path: path.name)
    if not content_files:
        raise ChallengeLoadError("The challenge content directory contains no JSON files.")

    try:
        signature = tuple((str(path), path.stat().st_mtime_ns, path.stat().st_size)
                          for path in content_files)
        bank = _load_bank(signature)
    except OSError as exc:
        raise ChallengeLoadError("The challenge bank could not be read.") from exc
    match = bank.get((normalized_id, normalized_version))
    if match is None:
        raise ChallengeLoadError(f"Challenge '{normalized_id}' version '{normalized_version}' was not found.")
    return match


@lru_cache(maxsize=4)
def _load_bank(signature: tuple[tuple[str, int, int], ...]) -> dict[tuple[str, str], LoadedChallenge]:
    """Validate once per on-disk bank version, not once per socket snapshot.

    Stat-based invalidation keeps development edits visible; digest pins still
    protect active rounds. An invalid file invalidates the entire bank.
    """
    bank = {}
    for filename, modified, size in signature:
        path = Path(filename)
        challenge = _read_challenge_file(path)
        stat = path.stat()
        if (stat.st_mtime_ns, stat.st_size) != (modified, size):
            raise ChallengeLoadError("Challenge content changed while loading; retry.")
        identity = (challenge.id, challenge.version)
        if identity in bank:
            raise ChallengeLoadError(f"Duplicate challenge version '{challenge.id}' {challenge.version} exists in the content bank.")
        bank[identity] = LoadedChallenge(challenge=challenge, content_digest=_canonical_digest(challenge))
    return bank
