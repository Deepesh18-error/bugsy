"""Process-local, fixed-label operational counters; no room or player data."""

from __future__ import annotations

from collections import Counter
from threading import Lock


METRIC_NAMES = (
    "room_created", "match_started", "match_ended", "player_reconnected",
    "runner_error", "runner_timeout",
)
EVENT_METRICS = {
    "MatchStarted": "match_started",
    "MatchEnded": "match_ended",
    "PlayerReconnected": "player_reconnected",
}


class OperationalMetrics:
    def __init__(self) -> None:
        self._counts: Counter[str] = Counter()
        self._lock = Lock()

    def increment(self, name: str, amount: int = 1) -> None:
        if name not in METRIC_NAMES or type(amount) is not int or amount < 1:
            raise ValueError("Unknown operational counter or invalid increment.")
        with self._lock:
            self._counts[name] += amount

    def observe_public_event(self, name: str, payload: dict[str, object]) -> None:
        counter = EVENT_METRICS.get(name)
        if counter is not None:
            self.increment(counter)
        elif name == "OfficialTestRunStatusChanged" and payload.get("status") == "error":
            self.increment("runner_error")

    def render(self, *, redis_up: bool) -> str:
        with self._lock:
            values = dict(self._counts)
        lines = ["# TYPE codemafia_api_up gauge", "codemafia_api_up 1",
                 "# TYPE codemafia_redis_up gauge", f"codemafia_redis_up {int(redis_up)}"]
        for name in METRIC_NAMES:
            lines.extend((f"# TYPE codemafia_{name}_total counter",
                          f"codemafia_{name}_total {values.get(name, 0)}"))
        return "\n".join(lines) + "\n"
