import styles from '../styles/CategoryVoteScreen.module.css';

export default function CategoryVoteScreen({
  categories,
  roomCode,
  voteCounts,
  selectedCategoryId,
  result,
  onVote,
  onContinue,
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

  return (
    <main className={styles.page}>
      <div className={styles.frame}>
        <header className={styles.topbar}>
          <a className={styles.brand} href="#category-vote" aria-label="CodeMafia home">
            <span className={styles.brandMark} aria-hidden="true">CM</span>
            <span>codemafia</span>
          </a>
          <div className={styles.matchMeta}>
            <span>ROOM</span>
            <strong>{roomCode}</strong>
          </div>
        </header>

        <section className={styles.content} id="category-vote">
          <div className={styles.heading}>
            <p className={styles.kicker}>
              <span className={styles.kickerDot} aria-hidden="true" />
              Match setup · step 1 of 2
            </p>
            <h1>Choose your<br /><span>debugging ground.</span></h1>
            <p className={styles.description}>
              Your crew will tackle challenges from one shared category. Cast
              your vote, then see where the group lands.
            </p>
            {isLive && deadlineAt && (
              <p className={styles.description}>
                Server vote deadline: <time dateTime={deadlineAt}>
                  {new Date(deadlineAt).toLocaleTimeString()}
                </time>
              </p>
            )}
          </div>

          <section className={styles.votePanel} aria-labelledby="vote-title">
            <div className={styles.panelHeader}>
              <div>
                <p className={styles.panelEyebrow}>ONE VOTE · LOCKS AFTER CASTING</p>
                <h2 id="vote-title">Pick a category</h2>
              </div>
              <span className={styles.ballotMark} aria-hidden="true">01</span>
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
                      {String(index + 1).padStart(2, '0')}
                    </span>
                    <span className={styles.categoryCopy}>
                      <span className={styles.categoryName}>{category.name}</span>
                      <span className={styles.categoryDescription}>{category.description}</span>
                    </span>
                    {!isLive && (
                      <span className={styles.voteCount}>
                        <strong>{voteCounts[category.id] ?? 0}</strong>
                        <span>{(voteCounts[category.id] ?? 0) === 1 ? 'vote' : 'votes'}</span>
                      </span>
                    )}
                    {isSelected && <span className={styles.selectionMark} aria-hidden="true">✓</span>}
                    {result && isWinner && <span className={styles.winnerTag}>SELECTED</span>}
                  </button>
                );
              })}
            </div>

            <div className={styles.voteStatus} aria-live="polite" role={status === 'error' ? 'alert' : 'status'}>
              {result && winningCategory ? (
                <>
                  <span className={styles.statusIcon} aria-hidden="true">✓</span>
                  <div>
                    <strong>{winningCategory.name} is selected for this match.</strong>
                    <p>
                      {result.wasTie
                        ? 'The preview used a repeatable room-code tie-break. The server will resolve real votes.'
                        : 'Your vote is locked. The preview ballots are complete.'}
                    </p>
                  </div>
                </>
              ) : (
                <>
                  <span className={styles.statusIconWaiting} aria-hidden="true">↗</span>
                  <div>
                    <strong>{selectedCategory
                      ? 'Vote recorded.'
                      : isSubmitting ? 'Recording your vote…' : 'Your vote is still open.'}</strong>
                    <p>
                      {statusMessage || (selectedCategory
                        ? `${selectedCategory.name} is your choice. Waiting for the group vote to resolve.`
                        : 'Choose one category. You cannot change it after voting.')}
                    </p>
                  </div>
                </>
              )}
            </div>

            {result && winningCategory && !isLive && (
              <button className={styles.continueButton} onClick={onContinue} type="button">
                Reveal my role <span aria-hidden="true">→</span>
              </button>
            )}

            {isLive ? (
              <p className={styles.previewNote} role={status === 'error' ? 'alert' : 'status'}>
                Votes are private until the server selects a category. Refreshing keeps your recorded ballot.
              </p>
            ) : (
              <p className={styles.previewNote}>
                This preview includes three simulated player votes. Vote counts and the result are local demo data.
              </p>
            )}
          </section>
        </section>

        <footer className={styles.footer}>
          <span>BUILD TOGETHER. TRUST CAREFULLY.</span>
          <span>CODEMAFIA · {isLive ? 'LIVE ROOM' : 'LOCAL PREVIEW'}</span>
        </footer>
      </div>
    </main>
  );
}
