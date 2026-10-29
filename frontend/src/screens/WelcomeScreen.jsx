import { useRef, useState } from 'react';
import { ROOM_CODE_CHARACTERS, ROOM_CODE_LENGTH } from '../api/rooms.js';
import { CHARACTERS, DEFAULT_CHARACTER_ID, getCharacter } from '../data/characters.js';
import CharacterSprite from '../components/CharacterSprite.jsx';
import styles from '../styles/WelcomeScreen.module.css';

const MAX_NAME_LENGTH = 24;

export default function WelcomeScreen({ onCreateRoom, onJoinRoom, onPreview, restoreError, onRetryResume, canRetryResume = true, isRestoring }) {
  const [displayName, setDisplayName] = useState('');
  const [avatarId, setAvatarId] = useState(DEFAULT_CHARACTER_ID);
  const [inspectedAvatarId, setInspectedAvatarId] = useState(null);
  const [roomCode, setRoomCode] = useState('');
  const [nameError, setNameError] = useState('');
  const [joinError, setJoinError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(null);
  const joinButtonRef = useRef(null);

  function getValidDisplayName() {
    const cleanedName = displayName.trim();

    if (cleanedName.length < 2) {
      setNameError('Enter at least two characters so your friends know who joined.');
      return null;
    }

    setNameError('');
    return cleanedName;
  }

  async function handleSubmit(event) {
    event.preventDefault();
    if (isSubmitting || isRestoring) return;

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

    try {
      if (action === 'join') await onJoinRoom(cleanedName, roomCode, avatarId);
      else await onCreateRoom(cleanedName, avatarId);
    } catch (error) {
      if (action === 'join') setJoinError(error.message);
      else setNameError(error.message);
    } finally {
      setIsSubmitting(null);
    }
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
          <a className={styles.brand} href="#welcome">
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

            {restoreError && (
              <p className={styles.errorText} role="alert">
                {restoreError}{' '}
                {canRetryResume && <button className={styles.retryButton} onClick={onRetryResume} type="button">Try reconnecting</button>}
              </p>
            )}
            <form aria-busy={Boolean(isSubmitting) || isRestoring} className={styles.entryForm} onSubmit={handleSubmit}>
            <label className={styles.fieldLabel} htmlFor="display-name">Your player name</label>
            <input
              autoComplete="nickname"
              className={styles.textInput}
                disabled={Boolean(isSubmitting) || isRestoring}
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
                <p className={styles.fieldHint} id="name-hint">2–{MAX_NAME_LENGTH} characters. Choose a name for this room.</p>
              )}
              <span aria-live="polite">{displayName.length}/{MAX_NAME_LENGTH}</span>
            </div>

            <fieldset className={styles.characterPicker} disabled={Boolean(isSubmitting) || isRestoring}>
              <legend className={styles.fieldLabel}>Choose your character</legend>
              <div className={styles.characterGrid}>
                {CHARACTERS.map((character) => (
                  <label
                    className={`${styles.characterChoice} ${avatarId === character.id ? styles.characterSelected : ''}`}
                    key={character.id}
                    onBlur={() => setInspectedAvatarId(null)}
                    onFocus={() => setInspectedAvatarId(character.id)}
                    onMouseEnter={() => setInspectedAvatarId(character.id)}
                    onMouseLeave={() => setInspectedAvatarId(null)}
                    title={`${character.inspiration} · ${character.note}`}
                  >
                    <input
                      checked={avatarId === character.id}
                      name="avatar-id"
                      onChange={() => setAvatarId(character.id)}
                      type="radio"
                      value={character.id}
                    />
                    <CharacterSprite animate={avatarId === character.id} decorative id={character.id} state={avatarId === character.id ? 'selected' : 'idle'} />
                    <span>{character.name}</span>
                  </label>
                ))}
              </div>
              <p className={styles.characterCredit} id="character-credit">
                Inspired by <strong>{getCharacter(inspectedAvatarId || avatarId).inspiration}</strong> · {getCharacter(inspectedAvatarId || avatarId).note}
                {(inspectedAvatarId || avatarId) === 'ledger-architect' && '. Fictional design; no verified likeness exists.'}
              </p>
            </fieldset>

              <div className={styles.createForm}>
              <button className={styles.createButton} disabled={Boolean(isSubmitting) || isRestoring} name="action" value="create" type="submit">
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
                  disabled={Boolean(isSubmitting) || isRestoring}
                  id="room-code"
                  maxLength={ROOM_CODE_LENGTH}
                  onChange={handleRoomCodeChange}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                      event.preventDefault();
                      event.currentTarget.form?.requestSubmit(joinButtonRef.current);
                    }
                  }}
                  placeholder="ABCDEFG2"
                  spellCheck="false"
                  value={roomCode}
                  aria-describedby={joinError ? 'join-error' : 'code-hint'}
                  aria-invalid={Boolean(joinError)}
                />
                <button className={styles.joinButton} disabled={Boolean(isSubmitting) || isRestoring} name="action" ref={joinButtonRef} value="join" type="submit">
                  {isSubmitting === 'join' ? 'Checking…' : 'Join'}
                </button>
              </div>
              {joinError ? (
                <p className={styles.errorText} id="join-error" role="alert">{joinError}</p>
              ) : (
                <p className={styles.fieldHint} id="code-hint">Ask the room host for their eight-character code.</p>
              )}
            </div>

            {isSubmitting && (
              <p className={styles.loadingFeedback} role="status">
                {isSubmitting === 'join' ? 'Checking the room code…' : 'Creating your room…'}
              </p>
            )}

            <p className={styles.previewNote}>
              <span aria-hidden="true">✳</span>
              Rooms and matches are live. Gather 4–5 players in separate browser sessions to play.
            </p>
            </form>
            <button className={styles.previewButton} disabled={Boolean(isSubmitting) || isRestoring} onClick={() => onPreview(displayName.trim() || 'Player', avatarId)} type="button">
              Explore the local match preview
            </button>
          </section>
        </section>

        <footer className={styles.footer}>
          <span>BUILD TOGETHER. TRUST CAREFULLY.</span>
          <span>CODEMAFIA · ROOM LOBBY</span>
        </footer>
      </div>
    </main>
  );
}
