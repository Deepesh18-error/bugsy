import { useRef, useState } from 'react';
import styles from '../styles/WelcomeScreen.module.css';

const MAX_NAME_LENGTH = 18;
const ROOM_CODE_LENGTH = 6;

export default function WelcomeScreen({ onCreateRoom, onJoinRoom }) {
  const [displayName, setDisplayName] = useState('');
  const [roomCode, setRoomCode] = useState('');
  const [nameError, setNameError] = useState('');
  const [joinError, setJoinError] = useState('');
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

    const action = event.nativeEvent.submitter?.value;
    const cleanedName = getValidDisplayName();
    if (!cleanedName) return;

    if (action === 'join') {
      setJoinError('');
      if (roomCode.length !== ROOM_CODE_LENGTH) {
        setJoinError(`Room codes are ${ROOM_CODE_LENGTH} characters long.`);
        return;
      }

      onJoinRoom(cleanedName, roomCode);
      return;
    }

    setJoinError('');
    onCreateRoom(cleanedName);
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

            <form className={styles.entryForm} onSubmit={handleSubmit}>
            <label className={styles.fieldLabel} htmlFor="display-name">Your player name</label>
            <input
              autoComplete="nickname"
              className={styles.textInput}
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
              <button className={styles.createButton} name="action" value="create" type="submit">
                <span>Create a room</span><span aria-hidden="true">↗</span>
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
                <button className={styles.joinButton} name="action" ref={joinButtonRef} value="join" type="submit">Join</button>
              </div>
              {joinError ? (
                <p className={styles.errorText} id="join-error" role="alert">{joinError}</p>
              ) : (
                <p className={styles.fieldHint} id="code-hint">Ask the room host for their six-character code.</p>
              )}
            </div>

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
