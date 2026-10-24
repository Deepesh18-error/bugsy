import styles from '../styles/RoleRevealScreen.module.css';

const ROLE_DETAILS = {
  civilian: {
    label: 'Civilian',
    symbol: '◎',
    accent: 'civilian',
    headline: 'Repair the code.',
    description:
      'Work with the crew to fix the challenge and get the tests passing. Pay attention to what changes, but remember: honest mistakes happen.',
    objectiveTitle: 'Your assignment',
    objective:
      'Help the team complete the coding challenge. A failing test can point to a bug, but it does not identify who caused it.',
  },
  impostor: {
    label: 'Impostor',
    symbol: '◉',
    accent: 'impostor',
    headline: 'Blend in. Break things.',
    description:
      'You are the hidden saboteur. Act like a teammate while quietly steering the shared code away from a passing solution.',
    objectiveTitle: 'Your assignment',
    objective:
      'Avoid suspicion and sabotage the challenge. A specific objective will appear when the coding arena is implemented.',
  },
};

export default function RoleRevealScreen({
  displayName,
  role,
  category,
  roomCode,
  message,
  onContinue,
  isLive = false,
  deadlineAt = null,
}) {
  const roleDetails = ROLE_DETAILS[role] ?? ROLE_DETAILS.civilian;
  const roleStyle = role === 'impostor' ? styles.impostor : styles.civilian;

  return (
    <main className={`${styles.page} ${roleStyle}`}>
      <div className={styles.frame}>
        <header className={styles.topbar}>
          <a className={styles.brand} href="#role-reveal" aria-label="CodeMafia home">
            <span className={styles.brandMark} aria-hidden="true">CM</span>
            <span>codemafia</span>
          </a>
          <div className={styles.roomMeta}>
            <span>ROOM</span>
            <strong>{roomCode}</strong>
          </div>
        </header>

        <section className={styles.content} id="role-reveal">
          <p className={styles.privateNotice}>
            <span aria-hidden="true">▣</span>
            PRIVATE ROLE · ONLY YOU SHOULD SEE THIS
          </p>

          <section className={styles.roleCard} aria-labelledby="role-title">
            <div className={styles.roleSymbol} aria-hidden="true">
              {roleDetails.symbol}
            </div>
            <p className={styles.revealLabel}>Your role, {displayName}</p>
            <p className={styles.roleName}>{roleDetails.label}</p>
            <h1 id="role-title">{roleDetails.headline}</h1>
            <p className={styles.description}>{roleDetails.description}</p>

            <div className={styles.divider} />

            <div className={styles.assignment}>
              <span className={styles.assignmentIcon} aria-hidden="true">
                {role === 'impostor' ? '!' : '⌘'}
              </span>
              <div>
                <h2>{roleDetails.objectiveTitle}</h2>
                <p>{roleDetails.objective}</p>
              </div>
            </div>

            <div className={styles.matchDetails}>
              <span>THIS MATCH</span>
              <strong>{category}</strong>
            </div>

            {!isLive && (
              <button className={styles.continueButton} onClick={onContinue} type="button">
                Continue to coding round <span aria-hidden="true">→</span>
              </button>
            )}
            <p className={styles.nextStep} aria-live="polite">
              {isLive
                ? `Keep this role private. Waiting for the server to start the coding round${deadlineAt ? `. Role reveal deadline: ${new Date(deadlineAt).toLocaleTimeString()}` : ''}.`
                : message || 'Keep this role private as you work through the challenge.'}
            </p>
          </section>

          {!isLive && (
            <p className={styles.previewNote}>
              This is a local preview reveal. Real roles must be assigned and delivered privately by the server.
            </p>
          )}
        </section>

        <footer className={styles.footer}>
          <span>BUILD TOGETHER. TRUST CAREFULLY.</span>
          <span>CODEMAFIA · {isLive ? 'LIVE ROOM' : 'LOCAL PREVIEW'}</span>
        </footer>
      </div>
    </main>
  );
}
