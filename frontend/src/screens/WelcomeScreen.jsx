import { useLayoutEffect, useRef, useState } from 'react';
import { ROOM_CODE_CHARACTERS, ROOM_CODE_LENGTH } from '../api/rooms.js';
import { CHARACTERS, DEFAULT_CHARACTER_ID, getCharacter } from '../data/characters.js';
import CharacterSprite from '../components/CharacterSprite.jsx';
import styles from '../styles/WelcomeScreen.module.css';

export default function WelcomeScreen({ onCreateRoom, onJoinRoom, onPreview, restoreError, onRetryResume, canRetryResume = true, isRestoring }) {
  const [mode, setMode] = useState(null);
  const [displayName, setDisplayName] = useState('');
  const [avatarId, setAvatarId] = useState(DEFAULT_CHARACTER_ID);
  const [inspectedAvatarId, setInspectedAvatarId] = useState(null);
  const [roomCode, setRoomCode] = useState('');
  const [nameError, setNameError] = useState('');
  const [joinError, setJoinError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const sceneRef = useRef(null);
  const consoleRef = useRef(null);
  const revealRef = useRef(null);
  const pageRef = useRef(null);

  useLayoutEffect(() => {
    const fitHatch = () => {
      if (!consoleRef.current || !sceneRef.current) return;
      const { width, height } = consoleRef.current.getBoundingClientRect();
      // SVG hatch is centred at (517,805), with dimensions 398 by 650.
      // Rotating the rocket swaps these axes. Keep clearance on all four sides.
      const rocketWidth = Math.max((height + 72) * 1034 / 398, (width + 72) * 1034 / 650);
      sceneRef.current.style.setProperty('--rocket-width', `${rocketWidth}px`);
    };
    fitHatch();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(fitHatch);
    observer.observe(consoleRef.current);
    return () => observer.disconnect();
  }, []);

  function moveLight(event) {
    if (event.pointerType === 'touch' || !revealRef.current || !pageRef.current) return;
    const bounds = revealRef.current.getBoundingClientRect();
    revealRef.current.style.setProperty('--light-x', `${event.clientX - bounds.left}px`);
    revealRef.current.style.setProperty('--light-y', `${event.clientY - bounds.top}px`);
    pageRef.current.style.setProperty('--page-light-x', `${event.clientX}px`);
    pageRef.current.style.setProperty('--page-light-y', `${event.clientY}px`);
  }

  function hideLight() {
    revealRef.current?.style.setProperty('--light-x', '-1000px');
    revealRef.current?.style.setProperty('--light-y', '-1000px');
    pageRef.current?.style.setProperty('--page-light-x', '-1000px');
    pageRef.current?.style.setProperty('--page-light-y', '-1000px');
  }

  function chooseMode(nextMode) {
    setMode(nextMode);
    setNameError('');
    setJoinError('');
  }

  async function handleSubmit(event) {
    event.preventDefault();
    if (isSubmitting || isRestoring || !mode) return;
    const name = displayName.trim();
    if (name.length < 2) { setNameError('Enter at least two characters.'); return; }
    setNameError('');
    if (mode === 'join') {
      if (roomCode.length !== ROOM_CODE_LENGTH) { setJoinError(`Room codes are ${ROOM_CODE_LENGTH} characters long.`); return; }
      if ([...roomCode].some((character) => !ROOM_CODE_CHARACTERS.includes(character))) {
        setJoinError('Use letters A–Z except I and O, and digits 2–9.'); return;
      }
    }
    setJoinError('');
    setIsSubmitting(true);
    try {
      if (mode === 'join') await onJoinRoom(name, roomCode, avatarId);
      else await onCreateRoom(name, avatarId);
    } catch (error) {
      if (mode === 'join') setJoinError(error.message);
      else setNameError(error.message);
    } finally { setIsSubmitting(false); }
  }

  return (
    <main className={styles.page} ref={pageRef} onPointerMove={moveLight} onPointerLeave={hideLight}>
      <div className={styles.content}>
        <header className={styles.hero}>
          <span className={styles.heroSpark} aria-hidden="true">✦</span>
          <h1>BUGSY<span className={styles.titleCursor} aria-hidden="true">_</span></h1>
          <p>FIX BUGS. FIND THE IMPOSTOR.</p>
        </header>
        <div className={styles.rocketStage} ref={sceneRef}>
        <div className={styles.shipReveal} aria-hidden="true" ref={revealRef}><img className={styles.rocketArt} src="/scenes/bugsy-pod.svg" alt="" /><span className={styles.enginePulse} /></div>
        <section className={styles.console} aria-label="Start playing" ref={consoleRef}>
          <div className={styles.consoleTop}><span>CREW CONSOLE</span><span className={styles.onlineLight} aria-hidden="true" /></div>
          {restoreError && <p className={styles.error} role="alert">{restoreError} {canRetryResume && <button type="button" onClick={onRetryResume}>Reconnect</button>}</p>}
          {!mode ? (
            <div className={styles.choiceMenu}>
              <button className={styles.primaryButton} disabled={isRestoring} onClick={() => chooseMode('create')} type="button">Create room <span aria-hidden="true">→</span></button>
              <button className={styles.secondaryButton} disabled={isRestoring} onClick={() => chooseMode('join')} type="button">Join room <span aria-hidden="true">→</span></button>
              <button className={styles.previewButton} disabled={isRestoring} onClick={() => onPreview(displayName.trim() || 'Player', avatarId)} type="button">Explore game preview</button>
            </div>
          ) : (
            <form className={styles.entryForm} aria-busy={isSubmitting || isRestoring} onSubmit={handleSubmit}>
              <div className={styles.formHeading}>
                <button className={styles.backButton} disabled={isSubmitting} onClick={() => chooseMode(null)} type="button" aria-label="Back to room options">←</button>
                <h2>{mode === 'create' ? 'Create room' : 'Join room'}</h2>
              </div>
              <label className={styles.fieldLabel} htmlFor="display-name">Your player name</label>
              <input autoComplete="nickname" className={styles.textInput} disabled={isSubmitting || isRestoring} id="display-name" maxLength={24}
                onChange={(event) => { setDisplayName(event.target.value); setNameError(''); }} placeholder="Enter a name" value={displayName} aria-invalid={Boolean(nameError)} />
              {nameError && <p className={styles.error} role="alert">{nameError}</p>}
              {mode === 'join' && <>
                <label className={styles.fieldLabel} htmlFor="room-code">Room code</label>
                <input autoCapitalize="characters" autoComplete="off" className={styles.textInput} disabled={isSubmitting || isRestoring} id="room-code" maxLength={ROOM_CODE_LENGTH}
                  onChange={(event) => { setRoomCode(event.target.value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, ROOM_CODE_LENGTH)); setJoinError(''); }}
                  placeholder="8-character code" spellCheck="false" value={roomCode} aria-invalid={Boolean(joinError)} />
                {joinError && <p className={styles.error} role="alert">{joinError}</p>}
              </>}
              <fieldset className={styles.characterPicker} disabled={isSubmitting || isRestoring}>
                <legend className={styles.fieldLabel}>Choose your character</legend>
                <div className={styles.characterGrid}>
                  {CHARACTERS.map((character) => (
                    <label className={`${styles.characterChoice} ${avatarId === character.id ? styles.characterSelected : ''}`} key={character.id}
                      onFocus={() => setInspectedAvatarId(character.id)} onBlur={() => setInspectedAvatarId(null)}
                      onMouseEnter={() => setInspectedAvatarId(character.id)} onMouseLeave={() => setInspectedAvatarId(null)}
                      title={`${character.inspiration} · ${character.note}`}>
                      <input checked={avatarId === character.id} name="avatar-id" onChange={() => setAvatarId(character.id)} type="radio" value={character.id} />
                      <CharacterSprite animate={avatarId === character.id} decorative id={character.id} state={avatarId === character.id ? 'selected' : 'idle'} />
                      <span>{character.name}</span>
                    </label>
                  ))}
                </div>
                <p className={styles.characterCredit} id="character-credit">Inspired by <strong>{getCharacter(inspectedAvatarId || avatarId).inspiration}</strong> · {getCharacter(inspectedAvatarId || avatarId).note}
                  {(inspectedAvatarId || avatarId) === 'ledger-architect' && '. Fictional design; no verified likeness exists.'}
                </p>
              </fieldset>
              <button className={styles.primaryButton} disabled={isSubmitting || isRestoring} type="submit">{isSubmitting ? 'Connecting…' : mode === 'create' ? 'Create a room' : 'Join'} <span aria-hidden="true">→</span></button>
            </form>
          )}
        </section>
        </div>
        <p className={styles.screenHint}>4–5 PLAYERS <span aria-hidden="true">·</span> ONE HIDDEN IMPOSTOR</p>
      </div>
      <div className={styles.spaceDecor} aria-hidden="true"><span className={styles.planet} /><span className={styles.asteroid} /><span className={styles.asteroid} /><span className={styles.star} /><span className={styles.star} /><span className={styles.star} /><span className={styles.star} /></div>
      <div className={styles.flashlight} aria-hidden="true" />
    </main>
  );
}
