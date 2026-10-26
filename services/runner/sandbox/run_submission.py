"""Tiny jailed operation server for one Python submission.

Trusted tests execute in the runner supervisor. This process exposes only a
Counter object's observable operations and never writes an official verdict.
"""

from __future__ import annotations

from contextlib import redirect_stdout
import json
from pathlib import Path
import sys


MAX_PLAYER_OUTPUT = 4_096
MAX_REPLY_BYTES = 4_096
_INPUT = sys.__stdin__.buffer
_OUTPUT = sys.__stdout__.buffer
_JSON_DUMPS = json.dumps


class DiscardPlayerOutput:
    def __init__(self) -> None:
        self.total = 0

    def write(self, value: str) -> int:
        size = len(value.encode("utf-8", errors="replace"))
        self.total += size
        if self.total > MAX_PLAYER_OUTPUT:
            raise RuntimeError("submission printed too much output")
        return len(value)

    def flush(self) -> None:
        pass


def _send(value: dict[str, object]) -> None:
    raw = _JSON_DUMPS(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(raw) + 1 > MAX_REPLY_BYTES:
        raise ValueError("sandbox reply exceeds the output budget")
    _OUTPUT.write(raw + b"\n")
    _OUTPUT.flush()


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] != "/work/submission.py":
        raise SystemExit(2)
    _send({"type": "ready", "protocol_version": 1})
    namespace: dict[str, object] = {"__name__": "submission", "__file__": sys.argv[1]}
    sink = DiscardPlayerOutput()
    load_failed = False
    try:
        source = Path(sys.argv[1]).read_text(encoding="utf-8")
        with redirect_stdout(sink):
            exec(compile(source, sys.argv[1], "exec"), namespace)
    except BaseException:
        load_failed = True

    instance: object | None = None
    for line in _INPUT:
        request: object = None
        try:
            request = json.loads(line)
            if not isinstance(request, dict) or set(request) - {"op", "name", "nonce", "args"}:
                raise ValueError("invalid operation")
            nonce = request.get("nonce")
            if not isinstance(nonce, str) or len(nonce) != 32:
                raise ValueError("invalid operation nonce")
            if load_failed:
                raise RuntimeError("submission could not load")
            operation = request.get("op")
            arguments = request.get("args", [])
            if not isinstance(arguments, list) or len(arguments) > 1:
                raise ValueError("invalid arguments")
            with redirect_stdout(sink):
                if operation == "construct" and request.get("name", "Counter") in {"Counter", "Stack", "Wallet"} and not arguments:
                    counter_type = namespace.get(request.get("name", "Counter"))
                    if not isinstance(counter_type, type):
                        raise TypeError("Counter class is missing")
                    instance = counter_type()
                    value: object = None
                elif operation == "call" and request.get("name") in {"increment", "decrement", "reset", "value", "push", "pop", "peek", "size", "deposit", "withdraw", "statement", "statement_is_copy"}:
                    if instance is None:
                        raise RuntimeError("Counter was not constructed")
                    if request["name"] == "statement_is_copy":
                        statement = instance.statement()
                        statement.append("alias-probe")
                        value = "alias-probe" not in instance.history
                    else:
                        value = getattr(instance, request["name"])(*arguments)
                elif operation == "read" and request.get("name") in {"count", "history", "balance"}:
                    if instance is None:
                        raise RuntimeError("Counter was not constructed")
                    value = getattr(instance, request["name"])
                else:
                    raise ValueError("operation is not allowed")
            _send({"nonce": nonce, "ok": True, "value": value})
        except BaseException:
            if isinstance(request, dict) and isinstance(request.get("nonce"), str):
                _send({"nonce": request["nonce"], "ok": False, "error_kind": "exception"})
            else:
                break


if __name__ == "__main__":
    main()
