import styles from '../styles/RoleRevealScreen.module.css';
import CharacterSprite from '../components/CharacterSprite.jsx';

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
  avatarId,
  role,
  category,
  roomCode,
  message,
  onContinue,
  isLive = false,
  deadlineAt = null,
}) {
  const roleDetails = Object.hasOwn(ROLE_DETAILS, role) ? ROLE_DETAILS[role] : null;
  const roleStyle = roleDetails
    ? role === 'impostor' ? styles.impostor : styles.civilian
    : styles.pending;

  return (
    <main className={`${styles.page} ${roleStyle}`}>
      <div className={styles.frame}>
        <header className={styles.topbar}>
          <a className={styles.brand} href="#role-reveal">
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
            {roleDetails ? 'PRIVATE ROLE · ONLY YOU SHOULD SEE THIS' : 'PRIVATE ROLE · WAITING FOR SERVER'}
          </p>

          <section className={styles.roleCard} aria-labelledby="role-title">
            {avatarId && <CharacterSprite className={styles.roleCharacter} decorative id={avatarId} state="selected" />}
            {roleDetails ? (
              <>
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
                    <p>{isLive && role === 'impostor'
                      ? 'Your private sabotage objective will appear when the coding round begins.'
                      : roleDetails.objective}</p>
                  </div>
                </div>
              </>
            ) : (
              <div role="status" aria-live="polite">
                <div className={styles.roleSymbol} aria-hidden="true">…</div>
                <p className={styles.revealLabel}>{displayName}, your role is private</p>
                <h1 id="role-title">Waiting for your role.</h1>
                <p className={styles.description}>
                  Your private role has not appeared in the authorized room snapshot yet. We will show it when the server sends it.
                </p>
              </div>
            )}

            {roleDetails && <div className={styles.matchDetails}>
              <span>THIS MATCH</span>
              <strong>{category}</strong>
            </div>}

            {!isLive && roleDetails && (
              <button className={styles.continueButton} onClick={onContinue} type="button">
                Continue to coding round <span aria-hidden="true">→</span>
              </button>
            )}
            {roleDetails && <p className={styles.nextStep} aria-live="polite">
              {isLive
                ? `Keep this role private. Waiting for the server to start the coding round${deadlineAt ? `. Role reveal deadline: ${new Date(deadlineAt).toLocaleTimeString()}` : ''}.`
                : message || 'Keep this role private as you work through the challenge.'}
            </p>}
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
