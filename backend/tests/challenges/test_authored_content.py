"""Run only repository-authored fixtures locally, never player submissions.

These checks validate content/test agreement, not Linux sandbox isolation.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'services' / 'runner'))
from app.challenges.loader import load_challenge
from challenges.registry import COUNTER, COUNTER_1_1, STACK, WALLET


class AuthoredSession:
    def __init__(self, source):
        self.namespace = {}
        exec(compile(source, '<trusted authored fixture>', 'exec'), self.namespace)

    async def construct(self, name='Counter'):
        self.instance = self.namespace[name]()

    async def call(self, method, *args):
        if method == 'statement_is_copy':
            statement = self.instance.statement()
            statement.append('alias-probe')
            return 'alias-probe' not in self.instance.history
        return getattr(self.instance, method)(*args)

    async def read(self, name):
        return getattr(self.instance, name)


def verdict(test, source):
    coroutine = test.run(AuthoredSession(source))
    try:
        coroutine.send(None)
    except StopIteration:
        return True
    except AssertionError:
        return False
    finally:
        coroutine.close()
    raise AssertionError('Authored fixture unexpectedly performed I/O')


class AuthoredContentTests(unittest.TestCase):
    def test_pins_tests_references_and_starter_defects(self):
        for spec in (COUNTER, COUNTER_1_1, STACK, WALLET):
            with self.subTest(challenge=spec.challenge_id, version=spec.version):
                loaded = load_challenge(spec.challenge_id, spec.version)
                self.assertEqual(loaded.content_digest, spec.content_digest)
                challenge = loaded.challenge
                if spec is not COUNTER:
                    fixture = Path(__file__).resolve().parents[3] / 'services' / 'runner' / 'tests' / 'fixtures' / (spec.challenge_id.replace('.', '_') + '.py')
                    self.assertEqual(fixture.read_text(), challenge.reference_solution)
                self.assertEqual([(t.id, t.test_definition_id) for t in challenge.tests],
                                 [(t.test_id, t.definition_id) for t in spec.tests])
                self.assertTrue(all(verdict(t, challenge.reference_solution) for t in spec.tests))
                results = {t.test_id: verdict(t, challenge.starter_code) for t in spec.tests}
                self.assertFalse(all(results.values()))
                self.assertFalse(results[challenge.sabotage_objectives[0].verification.test_id])

    def test_plausible_sabotage_has_only_declared_damage(self):
        edits = ((COUNTER_1_1, 'self.count -= 1', 'self.count -= 2'),
                 (STACK, 'return self.items.pop()', 'return self.items.pop(0)'),
                 (WALLET, ' or amount > self.balance', ''))
        for spec, before, after in edits:
            with self.subTest(challenge=spec.challenge_id):
                challenge = load_challenge(spec.challenge_id, spec.version).challenge
                source = challenge.reference_solution.replace(before, after)
                failed = {t.test_id for t in spec.tests if not verdict(t, source)}
                objective = challenge.sabotage_objectives[0]
                affected = {t.id for t in challenge.tests
                            if set(t.target_function_ids).intersection(objective.target_function_ids)}
                self.assertIn(objective.verification.test_id, failed)
                self.assertLessEqual(failed, affected)

    def test_statement_test_detects_aliasing_not_just_wrong_values(self):
        challenge = load_challenge(WALLET.challenge_id, WALLET.version).challenge
        alias = challenge.reference_solution.replace('return list(self.history)', 'return self.history')
        test = next(t for t in WALLET.tests if t.test_id == 'statement-copy')
        self.assertFalse(verdict(test, alias))
