import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { ROOM_CODE_CHARACTERS, ROOM_CODE_LENGTH } from '../api/rooms.js';
import { CHARACTERS, getCharacter } from '../data/characters.js';
import CharacterSprite from '../components/CharacterSprite.jsx';
import styles from '../styles/WelcomeScreen.module.css';

export default function WelcomeScreen({ onCreateRoom, onJoinRoom, onPreview, restoreError, onRetryResume, canRetryResume = true, isRestoring }) {
  const [mode, setMode] = useState(null);
  const [displayName, setDisplayName] = useState('');
  const [avatarId, setAvatarId] = useState(null);
  const [inspectedAvatarId, setInspectedAvatarId] = useState(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [characterError, setCharacterError] = useState('');
  const [roomCode, setRoomCode] = useState('');
  const [nameError, setNameError] = useState('');
  const [joinError, setJoinError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const sceneRef = useRef(null);
  const consoleRef = useRef(null);
  const revealRef = useRef(null);
  const pageRef = useRef(null);
  const pickerRef = useRef(null);
  const pickerTriggerRef = useRef(null);

  useEffect(() => {
    const syncMode = () => {
      const historyMode = window.history.state?.bugsyWelcomeMode;
      setMode(historyMode === 'create' || historyMode === 'join' ? historyMode : null);
      setPickerOpen(false);
      setNameError('');
      setJoinError('');
    };
    syncMode();
    window.addEventListener('popstate', syncMode);
    return () => window.removeEventListener('popstate', syncMode);
  }, []);

  useEffect(() => {
    if (!pickerOpen) return undefined;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    pickerRef.current?.focus();
    function handlePickerKey(event) {
      if (event.key === 'Escape') {
        setPickerOpen(false);
        return;
      }
      if (event.key !== 'Tab' || !pickerRef.current) return;
      const controls = [...pickerRef.current.querySelectorAll('button:not(:disabled)')];
      if (!controls.length) return;
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && (document.activeElement === first || document.activeElement === pickerRef.current)) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first.focus();
      }
    }
    window.addEventListener('keydown', handlePickerKey);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', handlePickerKey);
      pickerTriggerRef.current?.focus();
    };
  }, [pickerOpen]);

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
    if (nextMode === null && window.history.state?.bugsyWelcomeMode) {
      window.history.back();
      return;
    }
    if (nextMode !== null) {
      window.history.pushState({ ...window.history.state, bugsyWelcomeMode: nextMode }, '', window.location.href);
    }
    setMode(nextMode);
    setNameError('');
    setJoinError('');
  }

  function openPicker() {
    setInspectedAvatarId(null);
    setPickerOpen(true);
  }

  function chooseAvatar(nextAvatarId) {
    setAvatarId(nextAvatarId);
    setCharacterError('');
    setJoinError('');
    setPickerOpen(false);
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
      if (error.code === 'CHARACTER_TAKEN') {
        setCharacterError(error.message);
        openPicker();
      } else if (mode === 'join') setJoinError(error.message);
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
              <button aria-label={avatarId ? 'Change character' : 'Choose character'} className={styles.characterTrigger} disabled={isSubmitting || isRestoring} onClick={openPicker} ref={pickerTriggerRef} type="button">
                {avatarId ? <CharacterSprite decorative id={avatarId} state="selected" /> : <span className={styles.autoAvatar} aria-hidden="true">?</span>}
                <span><strong>{avatarId ? getCharacter(avatarId).name : 'Automatic character'}</strong><small>{avatarId ? 'Change character' : 'Choose character'}</small></span>
                <span aria-hidden="true">→</span>
              </button>
              <p className={styles.autoHint}>If you skip this, an available character is assigned when you enter the room.</p>
              <button className={styles.primaryButton} disabled={isSubmitting || isRestoring} type="submit">{isSubmitting ? 'Connecting…' : mode === 'create' ? 'Create a room' : 'Join'} <span aria-hidden="true">→</span></button>
            </form>
          )}
        </section>
        </div>
        <p className={styles.screenHint}>4–5 PLAYERS <span aria-hidden="true">·</span> ONE HIDDEN IMPOSTOR</p>
      </div>
      <div className={styles.spaceDecor} aria-hidden="true"><span className={styles.planet} /><span className={styles.asteroid} /><span className={styles.asteroid} /><span className={styles.star} /><span className={styles.star} /><span className={styles.star} /><span className={styles.star} /></div>
      <div className={styles.flashlight} aria-hidden="true" />
      {pickerOpen && <div className={styles.pickerBackdrop} onMouseDown={(event) => { if (event.target === event.currentTarget) setPickerOpen(false); }}>
        <section aria-label="Choose your character" aria-modal="true" className={styles.pickerDialog} ref={pickerRef} role="dialog" tabIndex={-1}>
          <header className={styles.pickerHeader}>
            <div><span>CREW ROSTER</span><h2>Choose your character</h2></div>
            <button aria-label="Close character picker" className={styles.pickerClose} onClick={() => setPickerOpen(false)} type="button">×</button>
          </header>
          {characterError && <p className={styles.pickerError} role="alert">{characterError}</p>}
          <div className={styles.pickerGrid}>
            {CHARACTERS.map((character) => <button aria-pressed={avatarId === character.id} className={`${styles.pickerCard} ${avatarId === character.id ? styles.pickerSelected : ''}`} key={character.id}
              onClick={() => chooseAvatar(character.id)} onFocus={() => setInspectedAvatarId(character.id)} onMouseEnter={() => setInspectedAvatarId(character.id)} type="button">
              <CharacterSprite animate={avatarId === character.id} className={styles.pickerSprite} decorative id={character.id} state={avatarId === character.id ? 'selected' : 'idle'} />
              <strong>{character.name}</strong><span className={styles.pickerCardCredit}>Inspired by {character.inspiration}<br />{character.note}</span>
            </button>)}
          </div>
          <footer className={styles.pickerFooter}>
            <p id="character-credit">{inspectedAvatarId ? <>Inspired by <strong>{getCharacter(inspectedAvatarId).inspiration}</strong> · {getCharacter(inspectedAvatarId).note}</> : 'Hover or focus a character to learn who inspired it.'}</p>
            <button className={styles.autoPickButton} onClick={() => chooseAvatar(null)} type="button">Let Bugsy assign one</button>
          </footer>
        </section>
      </div>}
    </main>
  );
}
