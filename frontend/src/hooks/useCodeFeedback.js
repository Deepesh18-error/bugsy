import { useCallback, useEffect, useRef, useState } from 'react';
import createFeedbackWorker from '#feedback-worker';

const FEEDBACK_TIMEOUT_MS = 20_000;
const AUTO_RUN_DEBOUNCE_MS = 800;
// A same-origin Worker is not an isolation boundary for untrusted shared code.
// Public builds use only the separate official runner until a credential-free,
// cross-origin browser sandbox is designed and reviewed.
export const BROWSER_FEEDBACK_ENABLED = import.meta.env.DEV;

/** Owns one disposable Python worker per run. terminate() stops a busy loop. */
export default function useCodeFeedback(roundKey, source, autoTests = null) {
  const activeRef = useRef(null);
  const [feedback, setFeedback] = useState({ status: 'idle', outcomes: [], source: null });

  const stopActive = useCallback(() => {
    const active = activeRef.current;
    if (!active) return;
    activeRef.current = null;
    clearTimeout(active.timeout);
    active.worker.terminate();
  }, []);

  useEffect(() => () => stopActive(), [roundKey, stopActive]);

  useEffect(() => {
    if (activeRef.current && activeRef.current.source !== source) {
      stopActive();
      setFeedback((previous) => ({ ...previous, status: 'stale' }));
    } else {
      setFeedback((previous) => previous.source !== null && previous.source !== source
        && previous.status === 'complete' ? { ...previous, status: 'stale' } : previous);
    }
  }, [source, stopActive]);

  const run = useCallback((tests) => {
    if (!BROWSER_FEEDBACK_ENABLED) {
      setFeedback({ status: 'error', outcomes: [], source: null,
        message: 'Browser checks are unavailable in public matches. Use official tests.' });
      return;
    }
    if (typeof source !== 'string' || !source.trim() || !Array.isArray(tests) || !tests.length) {
      setFeedback({ status: 'error', outcomes: [], source: null,
        message: 'Wait for the shared code and public checks to load.' });
      return;
    }
    stopActive();
    const runId = crypto.randomUUID();
    const worker = createFeedbackWorker();
    const active = { runId, worker, source, timeout: null };
    activeRef.current = active;
    setFeedback({ status: 'running', outcomes: [], source, message: '' });

    const finish = (next) => {
      if (activeRef.current !== active) return;
      stopActive();
      setFeedback({ ...next, source });
    };
    worker.onmessage = ({ data }) => {
      if (data?.runId !== runId) return;
      if (data.type === 'result' && Array.isArray(data.outcomes)
        && data.outcomes.length === tests.length
        && data.outcomes.every((item) => typeof item.test_id === 'string'
          && typeof item.passed === 'boolean')) {
        finish({ status: 'complete', outcomes: data.outcomes, message: '' });
      } else {
        finish({ status: 'error', outcomes: [],
          message: data?.message || 'Browser feedback returned an invalid result.' });
      }
    };
    worker.onerror = () => finish({ status: 'error', outcomes: [],
      message: 'The browser Python worker failed to load.' });
    active.timeout = setTimeout(() => finish({ status: 'timeout', outcomes: [],
      message: 'Browser feedback exceeded 20 seconds. Its worker was stopped.' }), FEEDBACK_TIMEOUT_MS);
    try {
      worker.postMessage({ type: 'run', runId, source, tests });
    } catch {
      finish({ status: 'error', outcomes: [], message: 'Could not start browser feedback.' });
    }
  }, [source, stopActive]);

  useEffect(() => {
    if (!BROWSER_FEEDBACK_ENABLED) return undefined;
    if (!Array.isArray(autoTests) || autoTests.length === 0 || !source.trim()) return undefined;
    const timer = window.setTimeout(() => run(autoTests), AUTO_RUN_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [roundKey, source, autoTests, run]);

  return { feedback, run, stop: stopActive };
}
