import { useRef, useState } from 'react';
import { PREVIEW_JOIN_CODES, ROOM_CODE_CHARACTERS, ROOM_CODE_LENGTH } from '../data/mockMatch.js';
import styles from '../styles/WelcomeScreen.module.css';

const MAX_NAME_LENGTH = 18;

export default function WelcomeScreen({ onCreateRoom, onJoinRoom }) {
  const [displayName, setDisplayName] = useState('');
  const [roomCode, setRoomCode] = useState('');
  const [nameError, setNameError] = useState('');
  const [joinError, setJoinError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(null);
  const joinButtonRef = useRef(null);

  function getValidDisplayName() {
    const cleanedName = displayName.trim();

    if (!cleanedName) {
      setNameError('Enter a name so your friends know who joined.');
      return null;
    }

    setNameError('');
    return cleanedName;
  }

  function handleSubmit(event) {
    event.preventDefault();
    if (isSubmitting) return;

    const action = event.nativeEvent.submitter?.value;
    const cleanedName = getValidDisplayName();
    if (!cleanedName) return;

    if (action === 'join') {
      setJoinError('');
      if (roomCode.length !== ROOM_CODE_LENGTH) {
        setJoinError(`Room codes are ${ROOM_CODE_LENGTH} characters long.`);
        return;
      }
      if ([...roomCode].some((character) => !ROOM_CODE_CHARACTERS.includes(character))) {
        setJoinError('Use letters A–Z except I and O, and digits 2–9.');
        return;
      }
    }

    setJoinError('');
    setIsSubmitting(action === 'join' ? 'join' : 'create');

    // A short local delay makes the pending state visible before the mock result.
    window.setTimeout(() => {
      if (action === 'join') {
        const result = onJoinRoom(cleanedName, roomCode);
        if (result?.error) {
          setJoinError(result.error);
          setIsSubmitting(null);
        }
        return;
      }

      onCreateRoom(cleanedName);
    }, 350);
  }

  function handleRoomCodeChange(event) {
    const normalizedCode = event.target.value
      .toUpperCase()
      .replace(/[^A-Z0-9]/g, '')
      .slice(0, ROOM_CODE_LENGTH);

    setRoomCode(normalizedCode);
    setJoinError('');
  }

  return (
    <main className={styles.page}>
      <div className={styles.frame}>
        <header className={styles.topbar}>
          <a className={styles.brand} href="#welcome" aria-label="CodeMafia home">
            <span className={styles.brandMark} aria-hidden="true">CM</span>
            <span>codemafia</span>
          </a>
          <span className={styles.topbarNote}>A co-op debugging game</span>
        </header>

        <section className={styles.content} id="welcome">
          <div className={styles.intro}>
            <p className={styles.kicker}>
              <span className={styles.kickerDot} aria-hidden="true" />
              Four minds. One suspicious bug.
            </p>
            <h1>Fix the code.<br /><span>Read the room.</span></h1>
            <p className={styles.description}>
              Team up to repair a broken program while one hidden saboteur tries
              to keep the bugs alive. Talk, debug, and decide who you trust.
            </p>

            <div className={styles.gameFacts} aria-label="Game details">
              <div><span className={styles.factValue}>4–5</span><span className={styles.factLabel}>players</span></div>
              <span className={styles.factDivider} aria-hidden="true" />
              <div><span className={styles.factValue}>Python</span><span className={styles.factLabel}>the crime scene</span></div>
              <span className={styles.factDivider} aria-hidden="true" />
              <div><span className={styles.factValue}>1</span><span className={styles.factLabel}>impostor</span></div>
            </div>
          </div>

          <section className={styles.entryCard} aria-labelledby="entry-title">
            <div className={styles.cardHeading}>
              <div>
                <p className={styles.cardEyebrow}>Ready when you are</p>
                <h2 id="entry-title">Join the investigation</h2>
              </div>
              <span className={styles.cardGlyph} aria-hidden="true">{'{ }'}</span>
            </div>

            <form aria-busy={Boolean(isSubmitting)} className={styles.entryForm} onSubmit={handleSubmit}>
            <label className={styles.fieldLabel} htmlFor="display-name">Your player name</label>
            <input
              autoComplete="nickname"
              className={styles.textInput}
              disabled={Boolean(isSubmitting)}
              id="display-name"
              maxLength={MAX_NAME_LENGTH}
              onChange={(event) => {
                setDisplayName(event.target.value);
                setNameError('');
              }}
              placeholder="e.g. Ada Lovelace"
              value={displayName}
              aria-describedby={nameError ? 'name-error' : 'name-hint'}
              aria-invalid={Boolean(nameError)}
            />
            <div className={styles.inputMeta}>
              {nameError ? (
                <p className={styles.errorText} id="name-error" role="alert">{nameError}</p>
              ) : (
                <p className={styles.fieldHint} id="name-hint">Up to {MAX_NAME_LENGTH} characters. You can change it later.</p>
              )}
              <span aria-live="polite">{displayName.length}/{MAX_NAME_LENGTH}</span>
            </div>

              <div className={styles.createForm}>
              <button className={styles.createButton} disabled={Boolean(isSubmitting)} name="action" value="create" type="submit">
                <span>{isSubmitting === 'create' ? 'Creating room…' : 'Create a room'}</span><span aria-hidden="true">↗</span>
              </button>
              </div>

            <div className={styles.separator}>
              <span /><span>or join your crew</span><span />
            </div>

            <div className={styles.joinForm}>
              <label className={styles.fieldLabel} htmlFor="room-code">Room code</label>
              <div className={styles.joinRow}>
                <input
                  autoCapitalize="characters"
                  autoComplete="off"
                  className={`${styles.textInput} ${styles.codeInput}`}
                  disabled={Boolean(isSubmitting)}
                  id="room-code"
                  maxLength={ROOM_CODE_LENGTH}
                  onChange={handleRoomCodeChange}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                      event.preventDefault();
                      event.currentTarget.form?.requestSubmit(joinButtonRef.current);
                    }
                  }}
                  placeholder="ABC123"
                  spellCheck="false"
                  value={roomCode}
                  aria-describedby={joinError ? 'join-error' : 'code-hint'}
                  aria-invalid={Boolean(joinError)}
                />
                <button className={styles.joinButton} disabled={Boolean(isSubmitting)} name="action" ref={joinButtonRef} value="join" type="submit">
                  {isSubmitting === 'join' ? 'Checking…' : 'Join'}
                </button>
              </div>
              {joinError ? (
                <p className={styles.errorText} id="join-error" role="alert">{joinError}</p>
              ) : (
                <p className={styles.fieldHint} id="code-hint">Ask the room host for their six-character code.</p>
              )}
              <details className={styles.previewCodes}>
                <summary>Preview room outcomes</summary>
                <p>Use these six-character codes to preview local join responses:</p>
                <ul>
                  <li><code>{PREVIEW_JOIN_CODES.available}</code> joins the sample room.</li>
                  <li><code>{PREVIEW_JOIN_CODES.full}</code> shows the room-full state.</li>
                  <li><code>{PREVIEW_JOIN_CODES.expired}</code> shows the expired-code state.</li>
                  <li><code>{PREVIEW_JOIN_CODES.serverError}</code> shows a simulated server error.</li>
                </ul>
                <p>Any other valid-format code shows the room-not-found state.</p>
              </details>
            </div>

            {isSubmitting && (
              <p className={styles.loadingFeedback} role="status">
                {isSubmitting === 'join' ? 'Checking the room code…' : 'Creating your preview room…'}
              </p>
            )}

            <p className={styles.previewNote}>
              <span aria-hidden="true">✳</span>
              Prototype preview: rooms and players are simulated on this device.
            </p>
            </form>
          </section>
        </section>

        <footer className={styles.footer}>
          <span>BUILD TOGETHER. TRUST CAREFULLY.</span>
          <span>CODEMAFIA · LOCAL PREVIEW</span>
        </footer>
      </div>
    </main>
  );
}
