import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react';
import PlayerCard from '../components/PlayerCard.jsx';
import StatusMessage from '../components/StatusMessage.jsx';
import TestResults from '../components/TestResults.jsx';
import { loadEditorHistory, loadEditorSession, restoreEditorRevision } from '../api/editor.js';
import { loadPublicFeedbackBundle, requestOfficialTestRun } from '../api/codeFeedback.js';
import useCodeFeedback from '../hooks/useCodeFeedback.js';
import useCollaborativeEditor from '../hooks/useCollaborativeEditor.js';
import styles from '../styles/ArenaScreen.module.css';

const CodeEditor = lazy(() => import('../components/CodeEditor.jsx'));

function timeLeft(deadlineAt) {
  return Math.max(0, Math.ceil((Date.parse(deadlineAt) - Date.now()) / 1000));
}

function formatTime(seconds) {
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
}

export default function LiveArena({ room, role, categoryName, roundNumber, totalRounds,
  deadlineAt, revisionId, connectionStatus, officialEvent, officialSnapshot,
  sendCommand, requestSnapshot }) {
  const [session, setSession] = useState(null);
  const [sessionError, setSessionError] = useState('');
  const [history, setHistory] = useState([]);
  const [historyError, setHistoryError] = useState('');
  const [restoreStatus, setRestoreStatus] = useState('');
  const [restoring, setRestoring] = useState(false);
  const [secondsLeft, setSecondsLeft] = useState(() => timeLeft(deadlineAt));
  const [collaborators, setCollaborators] = useState([]);
  const [accessibleMode, setAccessibleMode] = useState(false);
  const [source, setSource] = useState('');
  const [feedbackBundle, setFeedbackBundle] = useState(null);
  const [bundleError, setBundleError] = useState('');
  const [officialResult, setOfficialResult] = useState(null);
  const [officialStatus, setOfficialStatus] = useState('idle');
  const [officialError, setOfficialError] = useState('');
  const displayedOfficialResult = officialResult?.source_revision_id === revisionId
    ? officialResult : officialSnapshot ?? officialResult;
  const requestedRevisionRef = useRef(null);
  const ownPlayer = room.players.find((player) => player.id === room.currentPlayerId);
  const participant = useMemo(() => ({
    id: ownPlayer?.id, name: ownPlayer?.name,
    color: '#73d5b3',
  }), [ownPlayer?.id, ownPlayer?.name]);
  const editor = useCollaborativeEditor(session, participant, Boolean(session));
  const { feedback: provisional, run: runProvisional } = useCodeFeedback(
    `${room.code}:${roundNumber}`, source,
  );

  useEffect(() => {
    if (!editor.sharedText) { setSource(''); return undefined; }
    const sharedText = editor.sharedText;
    const update = () => setSource(sharedText.toString());
    update();
    sharedText.observe(update);
    return () => sharedText.unobserve(update);
  }, [editor.sharedText]);

  useEffect(() => {
    const controller = new AbortController();
    setFeedbackBundle(null);
    setBundleError('');
    loadPublicFeedbackBundle(room.code, roundNumber, controller.signal)
      .then((bundle) => setFeedbackBundle(bundle))
      .catch((error) => {
        if (error.name !== 'AbortError') setBundleError(error.message);
      });
    return () => controller.abort();
  }, [room.code, roundNumber]);

  useEffect(() => {
    if (officialEvent?.name !== 'OfficialTestResult') return;
    const payload = officialEvent.payload;
    if (payload?.source_revision_id !== revisionId) return;
    setOfficialResult(payload);
    setOfficialStatus('idle');
    setOfficialError('');
  }, [officialEvent, revisionId]);

  useEffect(() => {
    if (officialSnapshot?.source_revision_id !== revisionId) return;
    setOfficialStatus('idle');
    setOfficialError('');
  }, [officialSnapshot, revisionId]);

  useEffect(() => {
    if (officialStatus !== 'waiting') return undefined;
    // A result can commit even if its WebSocket event is lost. Refreshing the
    // authorized snapshot also resolves an already deduplicated retry.
    const refresh = window.setInterval(() => requestSnapshot?.(), 3_000);
    const timeout = window.setTimeout(() => {
      setOfficialStatus('idle');
      setOfficialError('No official result arrived yet. You can retry this saved revision.');
    }, 30_000);
    return () => { window.clearInterval(refresh); window.clearTimeout(timeout); };
  }, [officialStatus, requestSnapshot]);

  useEffect(() => {
    if ((officialStatus === 'waiting' || officialStatus === 'sending')
      && requestedRevisionRef.current !== revisionId) {
      setOfficialStatus('idle');
      setOfficialError('The code revision changed. Run official tests for the new saved revision.');
    }
  }, [revisionId, officialStatus]);

  useEffect(() => {
    let active = true;
    setSession(null);
    setSessionError('');
    loadEditorSession(room.code, roundNumber).then((next) => {
      if (active) setSession(next);
    }).catch((error) => {
      if (active) setSessionError(error.message);
    });
    return () => { active = false; };
  }, [room.code, roundNumber]);

  useEffect(() => {
    setSecondsLeft(timeLeft(deadlineAt));
    const id = window.setInterval(() => setSecondsLeft(timeLeft(deadlineAt)), 1000);
    return () => window.clearInterval(id);
  }, [deadlineAt]);

  useEffect(() => {
    if (!session) return undefined;
    let active = true;
    loadEditorHistory(session.documentId).then((items) => {
      if (active) { setHistory(items); setHistoryError(''); }
    }).catch((error) => {
      if (active) setHistoryError(error.message);
    });
    return () => { active = false; };
  }, [session, revisionId]);

  useEffect(() => {
    if (!editor.awareness) return undefined;
    const awareness = editor.awareness;
    const update = () => setCollaborators([...awareness.getStates().values()]
      .map((state) => state?.user?.name).filter(Boolean));
    update();
    awareness.on('change', update);
    return () => awareness.off('change', update);
  }, [editor.awareness]);

  async function handleRestore(revision) {
    if (!session || restoring || !editor.canEdit) return;
    setRestoring(true);
    setRestoreStatus('Restoring the selected revision…');
    try {
      await restoreEditorRevision(session, revision);
      setRestoreStatus('Revision restored. A new current revision was saved.');
    } catch (error) {
      setRestoreStatus(error.message);
    } finally {
      setRestoring(false);
    }
  }

  async function handleOfficialRun() {
    if (!revisionId || !sendCommand || officialStatus === 'sending') return;
    requestedRevisionRef.current = revisionId;
    setOfficialError('');
    setOfficialStatus('sending');
    try {
      await requestOfficialTestRun(sendCommand, revisionId);
      setOfficialStatus((current) => current === 'sending' ? 'waiting' : current);
    } catch (error) {
      setOfficialStatus('idle');
      setOfficialError(error.message || 'The official test request was rejected.');
    }
  }

  return (
    <main className={styles.page}>
      <header className={styles.topbar}>
        <span className={styles.brand}><span className={styles.brandMark} aria-hidden="true">CM</span> codemafia</span>
        <div className={styles.roundMeta}>ROUND {roundNumber}/{totalRounds} · {categoryName}</div>
        <div className={`${styles.timer} ${secondsLeft <= 15 ? styles.timerLow : ''}`} aria-label={`${formatTime(secondsLeft)} remaining`}>
          <span className={styles.timerLabel}>TIME LEFT</span><strong>{formatTime(secondsLeft)}</strong>
        </div>
        <div className={styles.roomCode}><span>ROOM</span><strong>{room.code}</strong></div>
      </header>
      <div className={styles.layout}>
        <section className={styles.challengePanel} aria-labelledby="live-challenge-title">
          <p className={styles.eyebrow}>THE CHALLENGE</p>
          <h1 id="live-challenge-title">{session?.challenge.title || 'Loading challenge…'}</h1>
          <p className={styles.challengeSummary}>{session?.challenge.prompt}</p>
          <section className={styles.objectiveCard} aria-label="Your role">
            <span className={`${styles.roleDot} ${role === 'impostor' ? styles.impostorDot : ''}`} aria-hidden="true" />
            <div><p className={styles.eyebrow}>YOUR ROLE</p><strong>{role === 'impostor' ? 'Impostor' : role === 'civilian' ? 'Civilian' : 'Waiting for role…'}</strong></div>
          </section>
          <TestResults bundle={feedbackBundle} bundleError={bundleError}
            provisional={provisional} official={displayedOfficialResult}
            officialStatus={officialStatus} officialError={officialError}
            revisionId={revisionId}
            canRun={editor.canEdit && connectionStatus === 'connected' && secondsLeft > 0}
            onRunProvisional={() => runProvisional(feedbackBundle?.tests)}
            onRunOfficial={handleOfficialRun} />
          <div className={styles.liveHistory}>
            <h2>Revision history</h2>
            <p>Current revision: <code>{revisionId || 'Waiting for server…'}</code></p>
            {historyError && <StatusMessage status="error">{historyError}</StatusMessage>}
            {restoreStatus && <StatusMessage status={restoreStatus.startsWith('Revision restored') ? 'success' : 'info'}>{restoreStatus}</StatusMessage>}
            {history.length === 0 ? <p>No saved edits yet.</p> : (
              <ol className={styles.historyList}>
                {[...history].reverse().map((item) => {
                  const author = room.players.find((player) => player.id === item.author_player_id);
                  return <li key={item.revision_id}>
                    <span><strong>{author?.name || 'Former player'}</strong> · {new Date(item.recorded_at).toLocaleTimeString()}</span>
                    <button type="button" disabled={!editor.canEdit || restoring || secondsLeft === 0
                      || item.revision_id === revisionId}
                      onClick={() => handleRestore(item.revision_id)}>Restore</button>
                  </li>;
                })}
              </ol>
            )}
          </div>
        </section>
        <section className={styles.editorPanel} aria-labelledby="live-editor-title">
          <div className={styles.editorHeader}>
            <div><p className={styles.eyebrow}>SHARED WORKSPACE · LIVE</p><h2 id="live-editor-title">challenge.py</h2></div>
            <span className={styles.languageBadge}>PYTHON</span>
          </div>
          {sessionError && <StatusMessage status="error">{sessionError}</StatusMessage>}
          {editor.error && <StatusMessage status="error">{editor.error}</StatusMessage>}
          <div className={styles.liveEditorToolbar}>
            <span role="status">Sync: {editor.status}</span>
            <button type="button" onClick={() => setAccessibleMode((value) => !value)}>
              {accessibleMode ? 'Use Monaco editor' : 'Use accessible text editor'}
            </button>
          </div>
          <Suspense fallback={<p>Loading editor…</p>}>
            {session && <CodeEditor sharedText={editor.sharedText} awareness={editor.awareness}
              canEdit={editor.canEdit && connectionStatus === 'connected' && secondsLeft > 0}
              preferAccessibleEditor={accessibleMode} />}
          </Suspense>
          <div className={styles.editorFooter}>
            <span><span className={styles.statusDot} aria-hidden="true" /> {editor.status === 'synced' ? 'Shared document synced' : 'Waiting for shared document'}</span>
            <span>{collaborators.length} collaborator{collaborators.length === 1 ? '' : 's'} online</span>
          </div>
          {collaborators.length > 0 && <p className={styles.collaborators}>Editing with {collaborators.join(', ')}</p>}
        </section>
        <aside className={styles.sideColumn} aria-label="Room players">
          <section className={styles.playersPanel}>
            <p className={styles.eyebrow}>IN THIS ROOM</p><h2>Players</h2>
            <ul className={styles.playerList}>{room.players.map((player) =>
              <PlayerCard className={styles.playerRow} key={player.id} player={player} variant="compact" />)}</ul>
          </section>
        </aside>
      </div>
      {secondsLeft === 0 && <div className={styles.timeUpBanner} role="status">Round deadline reached. Waiting for server result…</div>}
    </main>
  );
}
