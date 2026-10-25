import { loadPyodide, version as pyodideVersion } from 'pyodide';
import { FEEDBACK_HARNESS } from './feedbackHarness.js';

// This worker runs only public, provisional checks. The official runner never
// trusts its output. The main thread terminates the entire worker on timeout.
const PYODIDE_URL = `https://cdn.jsdelivr.net/pyodide/v${pyodideVersion}/full/`;
let pyodidePromise;

self.onmessage = async ({ data }) => {
  if (data?.type !== 'run' || typeof data.runId !== 'string'
    || typeof data.source !== 'string' || data.source.length > 65_536
    || !Array.isArray(data.tests) || data.tests.length > 16) return;

  try {
    pyodidePromise ??= loadPyodide({ indexURL: PYODIDE_URL });
    const pyodide = await pyodidePromise;
    // Python receives values through globals; source and test code are never
    // interpolated into the harness string.
    pyodide.globals.set('_feedback_source', data.source);
    pyodide.globals.set('_feedback_tests_json', JSON.stringify(data.tests));
    const raw = await pyodide.runPythonAsync(FEEDBACK_HARNESS);
    self.postMessage({ type: 'result', runId: data.runId, outcomes: JSON.parse(raw) });
  } catch {
    self.postMessage({ type: 'error', runId: data.runId,
      message: 'Browser Python feedback could not finish. Try again or use official tests.' });
  }
};
