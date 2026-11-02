import styles from '../styles/CategoryVoteScreen.module.css';

export default function CategoryVoteScreen({
  categories,
  roomCode,
  voteCounts,
  selectedCategoryId,
  result,
  onVote,
  onContinue,
  canContinue = true,
  isLive = false,
  isSubmitting = false,
  isDisabled = false,
  statusMessage = '',
  status = 'info',
  deadlineAt = null,
}) {
  const selectedCategory = categories.find(
    (category) => category.id === selectedCategoryId,
  );
  const winningCategory = result
    ? categories.find((category) => category.id === result.categoryId)
    : null;
  const voteState = winningCategory
    ? 'resolved'
    : selectedCategory ? 'voted' : isSubmitting ? 'pending' : 'open';
  const voteStatus = status === 'error' && statusMessage
    ? statusMessage
    : winningCategory
      ? canContinue ? 'Mission selected. Your role is ready.' : 'Mission selected. Preparing roles…'
      : isSubmitting ? 'Sending vote…' : selectedCategory
        ? 'Vote locked. Waiting for crew…' : isDisabled
          ? 'Reconnecting to crew…' : 'Choose one mission. Your vote locks in.';

  return (
    <main className={styles.page}>
      <div className={styles.stars} aria-hidden="true" />
      <div className={styles.planet} aria-hidden="true" />
      <div className={styles.orbit} aria-hidden="true" />
      <div className={styles.asteroid} aria-hidden="true" />
      <div className={styles.ship} aria-hidden="true"><div className={styles.shipWing} /><div className={styles.shipBody} /><div className={styles.shipEngine} /></div>
      <div className={styles.frame}>
        <header className={styles.topbar}>
          <a className={styles.brand} href="#category-vote">
            <span>BUGSY<span className={styles.brandCursor}>_</span></span>
          </a>
          <div className={styles.matchMeta}>
            <strong>ROOM {roomCode}</strong>
          </div>
        </header>

        <section className={styles.content} id="category-vote">
          <div className={styles.heading}>
            <p className={styles.kicker}>
              CREW BALLOT / 01
            </p>
            <h1>Choose the mission<span>.</span></h1>
          </div>

          <section className={styles.votePanel} aria-labelledby="vote-title">
            <div className={styles.panelHeader}>
              <span className={styles.consoleLight} aria-hidden="true" />
              <h2 id="vote-title">MISSION SELECTOR</h2>
              <span className={styles.deadline}>{deadlineAt && !result
                ? <>CLOSES <time dateTime={deadlineAt}>{new Date(deadlineAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time></>
                : 'ONE VOTE'}</span>
            </div>

            <div className={styles.categoryGrid}>
              {categories.map((category, index) => {
                const isSelected = selectedCategoryId === category.id;
                const isWinner = result?.categoryId === category.id;

                return (
                  <button
                    aria-pressed={isSelected}
                    className={`${styles.categoryCard} ${isSelected ? styles.selected : ''} ${isWinner ? styles.winner : ''}`}
                    disabled={Boolean(selectedCategoryId) || isSubmitting || isDisabled || Boolean(result)}
                    key={category.id}
                    onClick={() => onVote(category.id)}
                    type="button"
                  >
                    <span className={styles.categoryIndex} aria-hidden="true">
                      {['{ }', '</>', '++', '✦'][index % 4]}
                    </span>
                    <span className={styles.categoryCopy}>
                      <span className={styles.categoryName}>{category.name}</span>
                    </span>
                    {(!isLive || voteState === 'resolved') && (
                      <span className={styles.voteCount}>
                        <strong>{voteCounts[category.id] ?? 0}</strong> {(voteCounts[category.id] ?? 0) === 1 ? 'vote' : 'votes'}
                      </span>
                    )}
                    {isSelected && <span className={styles.selectionMark} aria-hidden="true">✓</span>}
                    {result && isWinner && <span className={styles.winnerTag}>SELECTED</span>}
                  </button>
                );
              })}
            </div>

            <div className={styles.voteStatus} aria-live="polite" role={status === 'error' ? 'alert' : 'status'}><span aria-hidden="true">{winningCategory ? '✦' : selectedCategory ? '✓' : '◉'}</span><strong>{voteStatus}</strong></div>

            {!isLive && result && winningCategory && (
              <button className={styles.continueButton} disabled={!canContinue} onClick={onContinue} type="button">
                Reveal role <span aria-hidden="true">→</span>
              </button>
            )}

            {!isLive && <p className={styles.previewNote}>LOCAL PREVIEW · SIMULATED CREW VOTES</p>}
          </section>
        </section>

      </div>
    </main>
  );
}
