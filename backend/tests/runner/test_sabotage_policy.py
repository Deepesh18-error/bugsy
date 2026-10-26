"""Adversarial attribution and bounded damage, using saved author chains."""
from dataclasses import replace
from datetime import timedelta
import unittest

from app.api.schemas import build_room_response
from app.game.models import OfficialTestResult, SabotageObjectiveProgress, ObjectiveStatus
from app.rooms.repository import EditorDocument, EditorRevision, StoredRoom
from app.rooms.serialization import serialize_room, deserialize_room
from app.runner.result_processor import RunnerResultProcessor
from app.runner.sabotage_policy import attributable_regression
from app.runner.contracts import TestFailureKind
from runner_support import NOW, LOADED, KEY, FakeRooms, FakeRunner, FakeConnections, coding_room, run_immediate
from test_runner_flow import signed_result
from app.runner.service import RunnerService
from app.game.commands import RequestOfficialTestRun


class SabotagePolicyTests(unittest.TestCase):
    def setUp(self):
        self.challenge = LOADED.challenge
        self.objective = self.challenge.sabotage_objectives[0]
        self.good = self.challenge.reference_solution
        self.bad = self.good.replace('self.count -= 1', 'self.count -= 2')
        baseline = OfficialTestResult('baseline', 'before', NOW - timedelta(seconds=2),
            passed_test_ids=tuple(t.id for t in self.challenge.tests), all_required_tests_passed=True)
        state = coding_room()
        current = replace(state.match.current_round, official_test_history=(baseline,),
            sabotage_objectives=(SabotageObjectiveProgress(self.objective.id),))
        self.state = replace(state, match=replace(state.match, current_round=current))
        self.document = EditorDocument('revision-1', self.bad, 'eA==', (
            EditorRevision('before', self.good, 'player-1', NOW - timedelta(seconds=3)),
            EditorRevision('revision-1', self.bad, 'player-4', NOW - timedelta(seconds=1)),
        ))
        self.rooms = FakeRooms(self.state, self.bad)
        self.rooms.document = self.document
        self.runner = FakeRunner()
        service = RunnerService(self.rooms, self.runner)
        run_immediate(service.enqueue_for_request(self.rooms.stored,
            RequestOfficialTestRun(request_id='request', player_id='player-4', source_revision_id='revision-1'), NOW))
        self.result = signed_result(self.runner.job, fail_test_id=self.objective.verification.test_id)

    def check(self, document=None, result=None):
        return attributable_regression(self.state, self.challenge, self.objective,
                                      document or self.document, result or self.result)

    def test_verified_edit_stays_private_and_does_not_end_match(self):
        self.assertTrue(self.check())
        connections = FakeConnections()
        processor = RunnerResultProcessor(self.rooms, self.runner, connections, signing_key=KEY)
        self.assertTrue(run_immediate(processor.process(self.result)))
        state = self.rooms.stored.state
        self.assertIsNone(state.match.result)
        self.assertEqual(state.match.current_round.sabotage_objectives[0].status, ObjectiveStatus.COMPLETED)
        self.assertEqual(state.match.sabotage_credits_used, 1)
        self.assertEqual(deserialize_room(serialize_room(state)), state)
        self.assertEqual(build_room_response(state, 'player-4').room.own_sabotage_credits_remaining, 2)
        civilian = build_room_response(state, 'player-1').room
        self.assertIsNone(civilian.own_sabotage_credits_remaining)
        self.assertIsNone(civilian.own_sabotage_cooldown_until)
        self.assertTrue(connections.private)
        self.assertFalse(any(event.name == 'SabotageObjectiveVerified' for _, event in connections.public))
        self.assertTrue(run_immediate(processor.process(self.result)))
        self.assertEqual(self.rooms.stored.state.match.sabotage_credits_used, 1)

    def test_civilian_then_impostor_comment_cannot_take_credit(self):
        history = (self.document.history[0],
            EditorRevision('civilian', self.bad, 'player-1', NOW - timedelta(seconds=1)),
            EditorRevision('revision-1', self.bad + '\n# hello', 'player-4', NOW))
        self.assertFalse(self.check(replace(self.document, history=history, source=history[-1].source)))

    def test_civilian_only_and_restore_are_not_sabotage(self):
        for edit in (replace(self.document.history[-1], author_player_id='player-1'),
                     replace(self.document.history[-1], restored_from_revision_id='old')):
            self.assertFalse(self.check(replace(self.document, history=(self.document.history[0], edit))))

    def test_missing_baseline_fails_closed(self):
        self.assertFalse(self.check(replace(self.document, history=self.document.history[1:])))

    def test_malformed_unrelated_and_comment_only_edits_fail(self):
        for source in ('invalid python !!!', self.bad.replace('self.count += 1', 'self.count += 2'),
                       self.good + '\n# harmless'):
            history = (self.document.history[0], replace(self.document.history[-1], source=source))
            self.assertFalse(self.check(replace(self.document, history=history, source=source)))

    def test_runtime_failure_and_unrelated_test_damage_fail(self):
        tests = tuple(t.model_copy(update={'failure_kind': TestFailureKind.EXCEPTION})
                      if not t.passed else t for t in self.result.tests)
        self.assertFalse(self.check(result=self.result.model_copy(update={'tests': tests})))
        tests = tuple(t.model_copy(update={'passed': False, 'failure_kind': TestFailureKind.ASSERTION})
                      if t.test_id == 'increment-changes-count' else t for t in self.result.tests)
        self.assertFalse(self.check(result=self.result.model_copy(update={'tests': tests})))

    def test_multiple_impostor_edits_are_attributable(self):
        history = (self.document.history[0],
            EditorRevision('intermediate', self.good + '\n# edit', 'player-4', NOW - timedelta(seconds=1)),
            self.document.history[-1])
        self.assertTrue(self.check(replace(self.document, history=history)))
