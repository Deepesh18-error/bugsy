"""Category vote fallback and reveal timing at the match boundary."""

from dataclasses import replace
from datetime import timedelta
from unittest import TestCase
from unittest.mock import patch

from app.game.events import CategorySelected
from app.game.models import DeadlineKind, GamePhase, MatchState
from app.game.outcomes import TransitionAccepted
from app.game.randomness import ScriptedChoiceSource
from app.realtime.match_setup import MatchSetupPolicy, make_phase_deadline, resolve_match_setup

from _builders import NOW, make_lobby


class CategoryFallbackTests(TestCase):
    @patch("app.realtime.match_setup.available_categories", return_value=("object-oriented", "back-end"))
    def test_no_ballots_uses_eligible_fallback_and_opens_reveal(self, _categories) -> None:
        state = replace(
            make_lobby(deadline=make_phase_deadline(DeadlineKind.CATEGORY_VOTE, NOW, 30)),
            phase=GamePhase.CATEGORY_VOTE,
            match=MatchState(),
        )
        outcome = resolve_match_setup(
            state, NOW + timedelta(seconds=30),
            choices=ScriptedChoiceSource(("back-end", "p4")),
            policy=MatchSetupPolicy(),
        )

        self.assertIsInstance(outcome, TransitionAccepted)
        self.assertEqual(outcome.state.phase, GamePhase.ROLE_REVEAL)
        self.assertEqual(outcome.state.match.selected_category_id, "back-end")
        self.assertEqual(outcome.state.phase_deadline.due_at, NOW + timedelta(seconds=45))
        selected = next(event for event in outcome.events if isinstance(event, CategorySelected))
        self.assertTrue(selected.used_fallback)
        self.assertEqual(selected.vote_counts, ())
