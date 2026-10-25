import { useCallback, useEffect, useRef, useState } from 'react';

const FEEDBACK_TIMEOUT_MS = 20_000;

/** Owns one disposable Python worker per run. terminate() stops a busy loop. */
export default function useCodeFeedback(roundKey, source) {
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
    if (typeof source !== 'string' || !source.trim() || !Array.isArray(tests) || !tests.length) {
      setFeedback({ status: 'error', outcomes: [], source: null,
        message: 'Wait for the shared code and public checks to load.' });
      return;
    }
    stopActive();
    const runId = crypto.randomUUID();
    const worker = new Worker(new URL('../workers/pythonFeedback.worker.js', import.meta.url),
      { type: 'module' });
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

  return { feedback, run, stop: stopActive };
}
