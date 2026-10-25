import assert from 'node:assert/strict';
import { test } from 'node:test';
import { loadPyodide } from 'pyodide';
import { FEEDBACK_HARNESS } from '../src/workers/feedbackHarness.js';

const tests = [
  { test_id: 'increment', test_code: 'c = Counter()\nc.increment()\nassert c.count == 1',
    failure_message: 'Increment failed.' },
  { test_id: 'decrement', test_code: 'c = Counter()\nc.decrement()\nassert c.count == -1',
    failure_message: 'Decrement failed.' },
];

test('browser Python checks report pass/fail without sharing test state', async () => {
  const pyodide = await loadPyodide();
  pyodide.globals.set('_feedback_source',
    'class Counter:\n    def __init__(self): self.count = 0\n    def increment(self): self.count += 1\n    def decrement(self): self.count -= 2');
  pyodide.globals.set('_feedback_tests_json', JSON.stringify(tests));
  const outcomes = JSON.parse(await pyodide.runPythonAsync(FEEDBACK_HARNESS));
  assert.deepEqual(outcomes, [
    { test_id: 'increment', passed: true, message: null },
    { test_id: 'decrement', passed: false, message: 'Decrement failed.' },
  ]);
});
