import styles from '../styles/VoteScreen.module.css';

const SKIP_VOTE = 'skip';

export default function VoteScreen({
  room,
  selectedTargetId,
  voteCounts,
  voteResult,
  isLocalPlayerEjected,
  onSelectTarget,
  onSubmitVote,
  onContinue,
}) {
  const livingPlayers = room.players.filter((player) => player.isAlive !== false);
  const voteTargetPlayers = livingPlayers.filter(
    (player) => player.id !== room.currentPlayerId,
  );
  const ejectedPlayer = voteResult?.ejectedPlayerId
    ? room.players.find((player) => player.id === voteResult.ejectedPlayerId)
    : null;
  const isSkipSelected = selectedTargetId === SKIP_VOTE;

  return (
    <main className={styles.page}>
      <div className={styles.frame}>
        <header className={styles.topbar}>
          <a className={styles.brand} href="#vote" aria-label="CodeMafia voting">
            <span className={styles.brandMark} aria-hidden="true">CM</span>
            <span>codemafia</span>
          </a>
          <div className={styles.roomMeta}>
            <span>ROOM</span>
            <strong>{room.code}</strong>
          </div>
        </header>

        <section className={styles.content} id="vote">
          <div className={styles.heading}>
            <p className={styles.eyebrow}>MEETING · BALLOT</p>
            <h1>{voteResult ? 'The vote is in.' : <>Who should leave<br /><span>the room?</span></>}</h1>
            <p className={styles.intro}>
              {voteResult
                ? 'The group result is shown below. Individual ballots stay private.'
                : 'Choose one living player or skip. Your ballot locks when you submit it.'}
            </p>
          </div>

          {!voteResult ? (
            <section className={styles.ballotPanel} aria-labelledby="ballot-title">
              <div className={styles.panelHeader}>
                <div>
                  <p className={styles.panelEyebrow}>PRIVATE BALLOT</p>
                  <h2 id="ballot-title">Select a player</h2>
                </div>
                <span className={styles.voterCount}>{livingPlayers.length} eligible</span>
              </div>

              <div className={styles.candidateList}>
                {voteTargetPlayers.map((player, index) => {
                  const isSelected = selectedTargetId === player.id;
                  return (
                    <button
                      aria-pressed={isSelected}
                      className={`${styles.candidate} ${isSelected ? styles.selected : ''}`}
                      key={player.id}
                      onClick={() => onSelectTarget(player.id)}
                      type="button"
                    >
                      <span className={styles.candidateNumber}>{String(index + 1).padStart(2, '0')}</span>
                      <span className={`${styles.avatar} ${styles[player.tone] ?? ''}`} aria-hidden="true">
                        {player.name.slice(0, 1).toUpperCase()}
                      </span>
                      <span className={styles.candidateName}>{player.name}</span>
                      <span className={styles.selectionMark} aria-hidden="true">{isSelected ? '✓' : '○'}</span>
                    </button>
                  );
                })}
              </div>

              <button
                aria-pressed={isSkipSelected}
                className={`${styles.skipButton} ${isSkipSelected ? styles.skipSelected : ''}`}
                onClick={() => onSelectTarget(SKIP_VOTE)}
                type="button"
              >
                <span aria-hidden="true">↷</span>
                Skip this vote
                <span className={styles.selectionMark} aria-hidden="true">{isSkipSelected ? '✓' : '○'}</span>
              </button>

              <div className={styles.ballotFooter}>
                <p>{selectedTargetId ? 'Your choice is selected. Submit to lock your ballot.' : 'Select a player or skip to continue.'}</p>
                <button
                  className={styles.submitButton}
                  disabled={!selectedTargetId}
                  onClick={onSubmitVote}
                  type="button"
                >
                  Submit vote <span aria-hidden="true">→</span>
                </button>
              </div>
              <p className={styles.previewNote}>The other players’ ballots are simulated in this local preview.</p>
            </section>
          ) : (
            <section className={styles.resultPanel} aria-labelledby="result-title" aria-live="polite">
              <p className={styles.panelEyebrow}>VOTE RESULT</p>
              <h2 id="result-title">
                {voteResult.reason === 'tie' && 'The vote was tied.'}
                {voteResult.reason === 'all-skipped' && 'Everyone skipped.'}
                {voteResult.reason === 'skip-wins' && 'Skip received the most votes.'}
                {voteResult.reason === 'ejected' && `${ejectedPlayer?.name ?? 'A player'} was ejected.`}
              </h2>
              <p className={styles.resultSummary}>
                {voteResult.reason === 'tie' && 'No one leaves the room. The round returns to play.'}
                {voteResult.reason === 'all-skipped' && 'No player received a vote, so no one leaves the room.'}
                {voteResult.reason === 'skip-wins' && 'The group chose not to eject anyone. The coding round will continue.'}
                {voteResult.reason === 'ejected' && (voteResult.isImpostorEjected
                  ? 'The impostor was identified. The civilians win this match.'
                  : 'The impostor remains. The coding round will continue.')}
              </p>

              <div className={styles.tally}>
                <p className={styles.panelEyebrow}>FINAL TALLY · INDIVIDUAL BALLOTS REMAIN PRIVATE</p>
                {Object.entries(voteCounts).map(([choiceId, count]) => {
                  const player = room.players.find((candidate) => candidate.id === choiceId);
                  const label = choiceId === SKIP_VOTE ? 'Skipped' : player?.name ?? 'Unknown player';
                  return (
                    <div className={styles.tallyRow} key={choiceId}>
                      <span>{label}</span>
                      <strong>{count} {count === 1 ? 'vote' : 'votes'}</strong>
                    </div>
                  );
                })}
              </div>

              {isLocalPlayerEjected ? (
                <p className={styles.localEjection} role="status">
                  Your preview player was ejected. The following result explains what happens next.
                </p>
              ) : null}

              <button className={styles.continueButton} onClick={onContinue} type="button">
                Continue to results
                <span aria-hidden="true">→</span>
              </button>
            </section>
          )}
        </section>

        <footer className={styles.footer}>
          <span>ONE BALLOT · PRIVATE UNTIL RESOLUTION</span>
          <span>CODEMAFIA · LOCAL PREVIEW</span>
        </footer>
      </div>
    </main>
  );
}
