import styles from '../styles/ResultsScreen.module.css';
import StatusMessage from '../components/StatusMessage.jsx';

export default function ResultsScreen({
  roomCode,
  roundNumber,
  totalRounds,
  result,
  onContinue,
  onRematch,
  isLive = false,
  isHost = false,
  isBusy = false,
  error = '',
  messageStatus = 'error',
  connectionStatus = 'connected',
}) {
  const isMatchResult = result.type === 'match';
  const resultLabel = isMatchResult ? 'MATCH COMPLETE' : 'ROUND COMPLETE';

  return (
    <main className={styles.page}>
      <div className={styles.frame}>
        <header className={styles.topbar}>
          <a className={styles.brand} href="#results" aria-label="CodeMafia results">
            <span className={styles.brandMark} aria-hidden="true">CM</span>
            <span>codemafia</span>
          </a>
          <div className={styles.roomMeta}>
            <span>ROOM</span>
            <strong>{roomCode}</strong>
          </div>
        </header>

        <section className={styles.content} id="results" aria-labelledby="results-title">
          <div className={styles.resultMark} aria-hidden="true">
            {isMatchResult ? '★' : '↗'}
          </div>
          <p className={`${styles.eyebrow} ${isMatchResult ? styles.matchEyebrow : ''}`}>
            {resultLabel} · ROUND {roundNumber}/{totalRounds}
          </p>
          <h1 id="results-title">{result.headline}</h1>
          <p className={styles.description}>{result.description}</p>

          <section className={styles.summaryCard} aria-labelledby="summary-title">
            <div className={styles.summaryHeader}>
              <div>
                <p className={styles.panelEyebrow}>WHAT HAPPENED</p>
                <h2 id="summary-title">{result.summaryTitle}</h2>
              </div>
              <span className={styles.outcomeTag}>{result.outcomeLabel}</span>
            </div>
            <p className={styles.summaryText}>{result.summary}</p>

            {result.voteCounts && (
              <div className={styles.tally}>
                <p className={styles.panelEyebrow}>FINAL VOTE TALLY</p>
                {Object.entries(result.voteCounts).map(([label, count]) => (
                  <div className={styles.tallyRow} key={label}>
                    <span>{label}</span>
                    <strong>{count} {count === 1 ? 'vote' : 'votes'}</strong>
                  </div>
                ))}
              </div>
            )}
          </section>

          <div className={styles.actions}>
            <button className={styles.primaryButton} onClick={onContinue} type="button"
              disabled={isLive && (isBusy || connectionStatus !== 'connected' || (!isMatchResult && !isHost))}>
              {isBusy ? 'Saving…' : isLive && !isMatchResult && !isHost ? 'Waiting for host'
                : result.continueLabel} <span aria-hidden="true">→</span>
            </button>
            {isMatchResult && (
              <button className={styles.secondaryButton} onClick={onRematch} type="button"
                disabled={isLive && (isBusy || connectionStatus !== 'connected')}>
                {isLive ? 'Request rematch' : 'Play another match'} <span aria-hidden="true">↻</span>
              </button>
            )}
          </div>

          {error && <StatusMessage status={messageStatus}>{error}</StatusMessage>}

          {!isLive && <p className={styles.previewNote}>
            {isMatchResult
              ? 'Match outcomes and rematches are local preview behavior. The server will own the real result.'
              : 'This round result is a local preview. The arena state is preserved until you continue.'}
          </p>}
          {isLive && !isMatchResult && !isHost && <p className={styles.previewNote} role="status">
            The host starts the next round. You will move there with the room.
          </p>}
        </section>

        <footer className={styles.footer}>
          <span>BUILD TOGETHER. TRUST CAREFULLY.</span>
          <span>CODEMAFIA · {isLive ? 'LIVE ROOM' : 'LOCAL PREVIEW'}</span>
        </footer>
      </div>
    </main>
  );
}
