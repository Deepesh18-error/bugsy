"""Black-box Counter checks driven from outside the source-code jail.

Each check receives a fresh jailed Counter process. Source can influence only
the observable replies to the operations we send; it cannot write a runner
result or choose which tests count toward victory.
"""

from __future__ import annotations

from typing import Protocol


class CounterSession(Protocol):
    async def construct(self) -> None: ...
    async def call(self, method: str) -> object: ...
    async def read(self, attribute: str) -> object: ...


async def counter_increment_changes_count(session: CounterSession) -> None:
    await session.construct()
    assert type(await session.read("count")) is int and await session.read("count") == 0
    assert await session.read("history") == []
    await session.call("increment")
    assert type(await session.read("count")) is int and await session.read("count") == 1
    assert await session.read("history") == ["inc"]


async def counter_decrement_subtracts_one(session: CounterSession) -> None:
    await session.construct()
    await session.call("decrement")
    assert type(await session.read("count")) is int and await session.read("count") == -1
    assert await session.read("history") == ["dec"]


async def counter_reset_sets_count_to_zero(session: CounterSession) -> None:
    await session.construct()
    await session.call("increment")
    await session.call("increment")
    await session.call("reset")
    assert type(await session.read("count")) is int and await session.read("count") == 0
    assert await session.read("history") == ["inc", "inc", "reset"]


async def counter_value_returns_count(session: CounterSession) -> None:
    await session.construct()
    await session.call("increment")
    await session.call("increment")
    await session.call("decrement")
    value = await session.call("value")
    assert type(value) is int and value == 1
    assert await session.read("history") == ["inc", "inc", "dec"]


async def counter_history_preserves_operation_order(session: CounterSession) -> None:
    await session.construct()
    for method in ("increment", "decrement", "increment", "reset", "decrement", "increment"):
        await session.call(method)
    assert await session.read("history") == ["inc", "dec", "inc", "reset", "dec", "inc"]
    assert type(await session.read("count")) is int and await session.read("count") == 0
    value = await session.call("value")
    assert type(value) is int and value == 0
