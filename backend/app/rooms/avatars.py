"""Stable public character identifiers shared by room requests and state."""

AVATAR_ORDER = (
    "linux-builder", "search-builder", "apple-inventor", "voxel-maker",
    "ledger-architect", "web-inventor", "python-creator", "apollo-coder",
    "compiler-pioneer", "c-creator",
)
AVATAR_IDS = frozenset(AVATAR_ORDER)
DEFAULT_AVATAR_ID = AVATAR_ORDER[0]


def validate_avatar_id(value: str) -> str:
    if value not in AVATAR_IDS:
        raise ValueError("Choose one of the available characters.")
    return value


def available_avatar_id(used: set[str]) -> str:
    """Pick the first free character when a player leaves the choice to us."""
    return next(avatar for avatar in AVATAR_ORDER if avatar not in used)
