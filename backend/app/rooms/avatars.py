"""Stable public character identifiers shared by room requests and state."""

AVATAR_IDS = frozenset({
    "linux-builder", "search-builder", "apple-inventor", "voxel-maker",
    "ledger-architect", "web-inventor", "python-creator", "apollo-coder",
    "compiler-pioneer", "c-creator",
})
DEFAULT_AVATAR_ID = "linux-builder"


def validate_avatar_id(value: str) -> str:
    if value not in AVATAR_IDS:
        raise ValueError("Choose one of the available characters.")
    return value
