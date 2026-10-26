import styles from '../styles/components/TestResults.module.css';

function ResultList({ tests, outcomes, emptyLabel }) {
  if (!tests?.length) return <p className={styles.detail}>{emptyLabel}</p>;
  const byId = new Map(outcomes.map((item) => [item.test_id, item]));
  return <ul className={styles.list}>
    {tests.map((test) => {
      const result = byId.get(test.test_id);
      return <li className={styles.row} key={test.test_id}>
        <span className={result ? (result.passed ? styles.pass : styles.fail) : styles.pending} aria-hidden="true">
          {result ? (result.passed ? '✓' : '×') : '○'}
        </span>
        <span className={styles.testName}>{test.name}
          {result?.message && <small className={styles.detail}>{result.message}</small>}
        </span>
        <span className={styles.tag}>{result ? (result.passed ? 'PASS' : 'FAIL') : 'NOT RUN'}</span>
      </li>;
    })}
  </ul>;
}

/** Distinct panels prevent a local pass from looking like a match verdict. */
export default function TestResults({ bundle, bundleError, provisional, official, officialStatus,
  officialError, revisionId, canRun, onRunProvisional, onRunOfficial,
  officialRunStatus = null, canFinalize = false, onFinalize, isFinalizing = false,
  browserFeedbackEnabled = true }) {
  const publicTests = bundle?.tests ?? [];
  const officialIsStale = official && official.source_revision_id !== revisionId;
  const provisionalOutcomes = provisional.status === 'complete' || provisional.status === 'stale'
    ? provisional.outcomes : [];
  const officialOutcomes = official?.tests ?? [];

  return <section className={styles.wrapper} aria-labelledby="feedback-title">
    <h2 id="feedback-title" className={styles.heading}>Code feedback</h2>
    {browserFeedbackEnabled ? <div className={styles.panel}>
      <div className={styles.panelHeader}>
        <h3>Browser check <span className={styles.provisionalLabel}>PROVISIONAL</span></h3>
        <button type="button" onClick={onRunProvisional}
          disabled={!canRun || !bundle || provisional.status === 'running'}>
          {provisional.status === 'running' ? 'Running…' : 'Run public checks'}
        </button>
      </div>
      <p className={styles.detail}>Runs public checks after editing settles. This browser result cannot decide the match. Only run shared code from players you trust.</p>
      {bundleError && <p className={styles.error} role="alert">{bundleError}</p>}
      {provisional.status === 'running' && <p className={styles.pending} role="status">Loading Python and checking the code…</p>}
      {provisional.status === 'stale' && <p className={styles.stale} role="status">Code changed. These browser results are stale; run again.</p>}
      {['timeout', 'error'].includes(provisional.status) && <p className={styles.error} role="alert">{provisional.message}</p>}
      <ResultList tests={publicTests} outcomes={provisionalOutcomes} emptyLabel="Public checks are loading…" />
    </div> : <p className={styles.detail}>Use official server checks to test the current shared code.</p>}
    <div className={styles.panel}>
      <div className={styles.panelHeader}>
        <h3>Server check <span className={styles.officialLabel}>OFFICIAL</span></h3>
        <button type="button" onClick={onRunOfficial}
          disabled={!canRun || !revisionId || officialStatus === 'sending'
            || officialStatus === 'waiting' || (official && !officialIsStale)}>
          {officialStatus === 'sending' ? 'Requesting…'
            : officialStatus === 'waiting' ? 'Waiting…'
              : official && !officialIsStale ? 'Result received' : 'Run official tests'}
        </button>
      </div>
      <p className={styles.detail}>Tests the server-saved revision <code>{revisionId || 'pending'}</code>. Recent edits may still be saving. Hidden checks stay on the server.</p>
      {officialStatus === 'waiting' && <p className={styles.pending} role="status">
        {officialRunStatus === 'running' ? 'Official checks are running…' : 'Official checks are queued…'}
      </p>}
      {officialError && <p className={styles.error} role="alert">{officialError}</p>}
      {officialIsStale && <p className={styles.stale} role="status">This official result belongs to an older revision.</p>}
      {official && !officialIsStale && <p className={official.all_required_tests_passed ? styles.pass : styles.fail} role="status">
        {official.all_required_tests_passed
          ? 'All required server checks passed. This result is a candidate until a player finalizes the current revision.'
          : 'The saved revision did not pass every required server check.'}
      </p>}
      {official?.all_required_tests_passed && !officialIsStale && <button type="button"
        onClick={onFinalize} disabled={!canFinalize || isFinalizing}>
        {isFinalizing ? 'Finalizing…' : 'Finalize verified solution'}
      </button>}
      <ResultList tests={officialOutcomes} outcomes={officialOutcomes} emptyLabel="No official result for this round yet." />
    </div>
  </section>;
}
