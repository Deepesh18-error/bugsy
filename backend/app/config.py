"""Deployment settings that must fail closed before a public API starts."""

from __future__ import annotations

from urllib.parse import urlsplit


def parse_bool(value: str, *, name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1"}:
        return True
    if normalized in {"false", "0"}:
        return False
    raise ValueError(f"{name} must be true or false.")


def validate_production_settings(
    *,
    environment: str,
    allowed_origins: tuple[str, ...],
    secure_cookie: bool,
    editor_websocket_url: str,
    editor_service_key: str,
    runner_result_key: str,
    redis_url: str | None,
    metrics_token: str | None = None,
    allow_draft_content: bool = False,
) -> None:
    """Reject development defaults and insecure public URLs in production.

    Redis may use a private network URL; its transport security is selected by
    the deployment topology and verified in the release checklist.
    """

    if environment not in {"development", "staging", "production"}:
        raise ValueError("CODEMAFIA_ENV must be development, staging, or production.")
    if environment == "development":
        return
    if environment == "production" and allow_draft_content:
        raise ValueError("Production cannot offer draft challenges.")
    if not secure_cookie:
        raise ValueError("Production guest cookies must use HTTPS-only Secure mode.")
    if not redis_url:
        raise ValueError("Production REDIS_URL must be set explicitly.")
    if not allowed_origins:
        raise ValueError("Production requires at least one HTTPS browser origin.")
    for origin in allowed_origins:
        parsed = urlsplit(origin)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.path or parsed.query or parsed.fragment):
            raise ValueError("Production browser origins must be HTTPS origins without paths.")
        if parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Production browser origins must be public hostnames.")
    editor = urlsplit(editor_websocket_url)
    if editor.scheme != "wss" or not editor.hostname or editor.username or editor.password:
        raise ValueError("Production editor WebSocket URL must use WSS without credentials.")
    if editor.hostname in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Production editor WebSocket URL must use a public hostname.")
    if (len(editor_service_key.encode("utf-8")) < 32
        or editor_service_key.startswith("replace-with")):
        raise ValueError("Production editor service key must contain at least 32 bytes.")
    if len(runner_result_key.encode("utf-8")) < 32:
        raise ValueError("Production runner result key must contain at least 32 bytes.")
    if metrics_token is None or len(metrics_token.encode("utf-8")) < 32:
        raise ValueError("Public environments require a 32+ byte metrics token.")
