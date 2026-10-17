"""Injectable choice sources for roles and deterministic tie resolution."""

from __future__ import annotations

from collections.abc import Sequence
import random
import secrets
from typing import Protocol, TypeVar


ChoiceT = TypeVar("ChoiceT")


class ChoiceSource(Protocol):
    """Interface expected by code that needs one choice from candidates."""

    def choose_one(self, candidates: Sequence[ChoiceT], /) -> ChoiceT:
        """Return exactly one member of a non-empty candidate sequence."""


class SecureChoiceSource:
    """Use operating-system randomness for live role and tie selections."""

    def choose_one(self, candidates: Sequence[ChoiceT], /) -> ChoiceT:
        if not candidates:
            raise ValueError("cannot choose from an empty candidate sequence")
        return secrets.choice(candidates)


class SeededChoiceSource:
    """Use a private seeded PRNG for repeatable match simulations.

    Replay is deterministic when the seed, candidate ordering, Python runtime,
    and sequence of choices stay the same. Persisting the actual selected IDs
    is still the strongest record for long-term replay across code changes.
    """

    def __init__(self, seed: int | str | bytes) -> None:
        self._random = random.Random(seed)

    def choose_one(self, candidates: Sequence[ChoiceT], /) -> ChoiceT:
        if not candidates:
            raise ValueError("cannot choose from an empty candidate sequence")
        return self._random.choice(candidates)


class ScriptedChoiceSource:
    """Return pre-recorded choices and verify each belongs to its candidates.

    Useful for replaying a scenario from logged selections without depending
    on an RNG seed or on random-number call order.
    """

    def __init__(self, choices: Sequence[object]) -> None:
        self._choices = tuple(choices)
        self._next_index = 0

    def choose_one(self, candidates: Sequence[ChoiceT], /) -> ChoiceT:
        if not candidates:
            raise ValueError("cannot choose from an empty candidate sequence")
        if self._next_index >= len(self._choices):
            raise ValueError("no scripted choice remains")
        choice = self._choices[self._next_index]
        if choice not in candidates:
            raise ValueError("scripted choice is not in the candidate sequence")
        self._next_index += 1
        return choice  # type: ignore[return-value]

    @property
    def choices_consumed(self) -> int:
        return self._next_index
