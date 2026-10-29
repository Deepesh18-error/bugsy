"""Trusted parent-side checks for the C++ score challenge."""

from __future__ import annotations


async def cpp_add_points(session) -> None:
    assert await session.score("add", 3, 4) == 7
    assert await session.score("add", 5, -2) == 3


async def cpp_subtract_points(session) -> None:
    assert await session.score("subtract", 9, 3) == 6
    assert await session.score("subtract", 0, 4) == -4


async def cpp_reset_score(session) -> None:
    assert await session.score("reset", 12, 0) == 0
    assert await session.score("reset", -5, 0) == 0


async def cpp_score_sequence(session) -> None:
    score = await session.score("add", 7, 6)
    score = await session.score("subtract", score, 4)
    assert score == 9
    score = await session.score("reset", score, 0)
    assert score == 0
    assert await session.score("subtract", score, 2) == -2
