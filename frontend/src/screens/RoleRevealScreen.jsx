import styles from '../styles/RoleRevealScreen.module.css';
import CharacterSprite from '../components/CharacterSprite.jsx';

const ROLE_DETAILS = {
  civilian: {
    label: 'Civilian',
    objective: 'Fix the code. Find the saboteur.',
  },
  impostor: {
    label: 'Impostor',
    objective: 'Blend in. Keep the bugs alive.',
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
      <div className={styles.stars} aria-hidden="true" />
      <div className={styles.revealBeam} aria-hidden="true" />
      <div className={styles.frame}>
        <header className={styles.topbar}>
          <a className={styles.brand} href="#role-reveal">
            <span>BUGSY<span className={styles.brandCursor}>_</span></span>
          </a>
          <div className={styles.roomMeta}>
            <strong>ROOM {roomCode}</strong>
          </div>
        </header>

        <section className={styles.content} id="role-reveal">
          <section className={styles.roleCard} aria-labelledby="role-title">
            {roleDetails ? (
              <>
                <p className={styles.privateNotice}>PRIVATE ROLE · {displayName}</p>
                <div className={styles.characterStage}>
                  <span className={styles.halo} aria-hidden="true" />
                  {avatarId && <CharacterSprite className={styles.roleCharacter} decorative id={avatarId} state={role === 'impostor' ? 'meeting' : 'ready'} />}
                </div>
                <h1 id="role-title" className={styles.roleName}>{roleDetails.label}</h1>
                <p className={styles.objective}>{roleDetails.objective}</p>
              </>
            ) : (
              <div role="status" aria-live="polite">
                <div className={styles.roleSymbol} aria-hidden="true">?</div>
                <h1 id="role-title">Waiting for your role.</h1>
                <p className={styles.objective}>Waiting for the server…</p>
              </div>
            )}

            {roleDetails && <div className={styles.matchDetails}>
              <span>MISSION · {category}</span>
            </div>}

            {!isLive && roleDetails && (
              <button className={styles.continueButton} onClick={onContinue} type="button">
                Enter mission <span aria-hidden="true">→</span>
              </button>
            )}
            {roleDetails && <p className={styles.nextStep} aria-live="polite">
              {isLive ? 'Waiting for crew to enter the coding round…' : message || 'Keep your role secret.'}
            </p>}
          </section>

          {!isLive && <p className={styles.previewNote}>LOCAL PREVIEW · ROLES ARE SIMULATED</p>}
        </section>
      </div>
    </main>
  );
}
