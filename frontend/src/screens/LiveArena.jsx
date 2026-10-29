import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react';
import PlayerCard from '../components/PlayerCard.jsx';
import ChatPanel from '../components/ChatPanel.jsx';
import StatusMessage from '../components/StatusMessage.jsx';
import TestResults from '../components/TestResults.jsx';
import SabotageObjectives from '../components/SabotageObjectives.jsx';
import { loadEditorHistory, loadEditorSession, restoreEditorRevision } from '../api/editor.js';
import { loadPublicFeedbackBundle, requestOfficialTestRun } from '../api/codeFeedback.js';
import useCodeFeedback, { BROWSER_FEEDBACK_ENABLED } from '../hooks/useCodeFeedback.js';
import useCollaborativeEditor from '../hooks/useCollaborativeEditor.js';
import styles from '../styles/ArenaScreen.module.css';

const CodeEditor = lazy(() => import('../components/CodeEditor.jsx'));

function timeLeft(deadlineAt) {
  const deadline = typeof deadlineAt === 'string' ? Date.parse(deadlineAt) : NaN;
  return Number.isFinite(deadline) ? Math.max(0, Math.ceil((deadline - Date.now()) / 1000)) : 0;
}

function formatTime(seconds) {
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
}

export default function LiveArena({ room, role, categoryName, roundNumber, totalRounds,
  deadlineAt, revisionId, connectionStatus, officialEvent, officialSnapshot, officialRuns,
  runStatusEvent,
  ownObjectives = [], sabotageCredits = null, sabotageCooldownUntil = null, ownMeetingsUsed = 0, meetingCooldownUntil = null,
  chatMessages = [], onSendChat, canSendChat = false,
  sendCommand, requestSnapshot }) {
  const [session, setSession] = useState(null);
  const [sessionError, setSessionError] = useState('');
  const [history, setHistory] = useState([]);
  const [historyError, setHistoryError] = useState('');
  const [restoreStatus, setRestoreStatus] = useState('');
  const [restoreStatusKind, setRestoreStatusKind] = useState('info');
  const [restoring, setRestoring] = useState(false);
  const [secondsLeft, setSecondsLeft] = useState(() => timeLeft(deadlineAt));
  const [cooldownSeconds, setCooldownSeconds] = useState(() => timeLeft(meetingCooldownUntil));
  const [collaborators, setCollaborators] = useState([]);
  const [accessibleMode, setAccessibleMode] = useState(false);
  const [source, setSource] = useState('');
  const [feedbackBundle, setFeedbackBundle] = useState(null);
  const [bundleError, setBundleError] = useState('');
  const [officialResult, setOfficialResult] = useState(null);
  const [officialStatus, setOfficialStatus] = useState('idle');
  const [officialError, setOfficialError] = useState('');
  const [meetingBusy, setMeetingBusy] = useState(false);
  const [meetingError, setMeetingError] = useState('');
  const [finalizing, setFinalizing] = useState(false);
  const [finalizeError, setFinalizeError] = useState('');
  const displayedOfficialResult = officialResult?.source_revision_id === revisionId
    ? officialResult : officialSnapshot ?? officialResult;
  const requestedRevisionRef = useRef(null);
  const ownPlayer = room.players.find((player) => player.id === room.currentPlayerId);
  const latestRun = [...(officialRuns ?? [])].reverse()
    .find((run) => run.source_revision_id === revisionId);
  const participant = useMemo(() => ({
    id: ownPlayer?.id, name: ownPlayer?.name,
    color: '#73d5b3',
  }), [ownPlayer?.id, ownPlayer?.name]);
  const editor = useCollaborativeEditor(session, participant,
    Boolean(session) && connectionStatus === 'connected');
  const isCpp = session?.challenge?.language === 'cpp';
  const { feedback: provisional, run: runProvisional } = useCodeFeedback(
    `${room.code}:${roundNumber}`, source,
    BROWSER_FEEDBACK_ENABLED && !isCpp ? feedbackBundle?.tests : null,
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
    setFeedbackBundle(null);
    setBundleError('');
    if (!session?.challenge || session.challenge.language === 'cpp') return undefined;
    const controller = new AbortController();
    loadPublicFeedbackBundle(room.code, roundNumber, controller.signal)
      .then((bundle) => setFeedbackBundle(bundle))
      .catch((error) => {
        if (error.name !== 'AbortError') setBundleError(error.message);
      });
    return () => controller.abort();
  }, [room.code, roundNumber, session?.challenge?.language]);

  useEffect(() => {
    if (officialEvent?.name !== 'OfficialTestResult') return;
    const payload = officialEvent.payload;
    if (payload?.source_revision_id !== revisionId) return;
    setOfficialResult(payload);
    setOfficialStatus('idle');
    setOfficialError('');
  }, [officialEvent, revisionId]);

  useEffect(() => {
    if (runStatusEvent?.name !== 'OfficialTestRunStatusChanged') return;
    const run = runStatusEvent.payload;
    if (run?.source_revision_id !== revisionId) return;
    if (run.status === 'queued' || run.status === 'running') {
      requestedRevisionRef.current = revisionId;
      setOfficialStatus('waiting');
      setOfficialError('');
    } else if (run.status === 'error') {
      setOfficialStatus('idle');
      setOfficialError('Official tests could not finish. You can retry this saved revision.');
    } else if (run.status === 'stale') {
      setOfficialStatus('idle');
      setOfficialError('This test run became stale. Run tests again for the current revision.');
    }
  }, [runStatusEvent, revisionId]);

  useEffect(() => {
    const latest = [...(officialRuns ?? [])]
      .reverse()
      .find((run) => run.source_revision_id === revisionId);
    if (!latest) return;
    if (latest.status === 'error') {
      setOfficialStatus('idle');
      setOfficialError('Official tests could not finish. You can retry this saved revision.');
    } else if (latest.status === 'stale') {
      setOfficialStatus('idle');
      setOfficialError('This test run became stale. Run tests again for the current revision.');
    } else if (latest.status === 'queued' || latest.status === 'running') {
      requestedRevisionRef.current = revisionId;
      setOfficialStatus('waiting');
      setOfficialError('');
    }
  }, [officialRuns, revisionId]);

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
    const update = () => setCooldownSeconds(timeLeft(meetingCooldownUntil));
    update();
    const id = window.setInterval(update, 1000);
    return () => window.clearInterval(id);
  }, [meetingCooldownUntil]);

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
    setRestoreStatusKind('info');
    try {
      await restoreEditorRevision(session, revision);
      setRestoreStatus('Revision restored. A new current revision was saved.');
      setRestoreStatusKind('success');
    } catch (error) {
      setRestoreStatus(error.message);
      setRestoreStatusKind('error');
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

  async function handleCallMeeting() {
    if (meetingBusy || ownMeetingsUsed > 0 || cooldownSeconds > 0
      || !ownPlayer?.isAlive || connectionStatus !== 'connected' || secondsLeft === 0) return;
    setMeetingBusy(true);
    setMeetingError('');
    try {
      await sendCommand({ name: 'call_emergency_meeting' });
      requestSnapshot?.();
    } catch (error) {
      setMeetingError(error.message || 'The meeting could not be called.');
    } finally {
      setMeetingBusy(false);
    }
  }

  async function handleFinalize() {
    if (finalizing || !revisionId) return;
    setFinalizing(true);
    setFinalizeError('');
    try {
      await sendCommand({ name: 'finalize_solution', source_revision_id: revisionId });
      requestSnapshot?.();
    } catch (error) {
      setFinalizeError(error.message || 'The verified solution could not be finalized.');
    } finally {
      setFinalizing(false);
    }
  }

  return (
    <main className={styles.page}>
      <header className={styles.topbar}>
        <span className={styles.brand}><span className={styles.brandMark} aria-hidden="true">CM</span> codemafia</span>
        <div className={styles.roundMeta}>ROUND {roundNumber}/{totalRounds} · {categoryName}</div>
        <div className={`${styles.timer} ${secondsLeft <= 15 ? styles.timerLow : ''}`} role="timer" aria-live="off" aria-label={`${formatTime(secondsLeft)} remaining`}>
          <span className={styles.timerLabel}>TIME LEFT</span><strong>{formatTime(secondsLeft)}</strong>
        </div>
        <span className="srOnly" role="status">
          {secondsLeft > 0 && secondsLeft <= 15 ? '15 seconds or less remain in this coding round.'
            : secondsLeft > 15 && secondsLeft <= 60 ? 'One minute or less remains in this coding round.' : ''}
        </span>
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
          {role === 'impostor' && <SabotageObjectives objectives={ownObjectives} credits={sabotageCredits}
            cooldownSeconds={timeLeft(sabotageCooldownUntil)} />}
          <p className={styles.challengeSummary}>Sabotage can win only at the round deadline, after at least 30 seconds to respond. Editing or restoring the code clears its current verification. Repair and rerun tests, or call a meeting.</p>
          <TestResults bundle={feedbackBundle} bundleError={bundleError}
            browserFeedbackEnabled={BROWSER_FEEDBACK_ENABLED && !isCpp}
            provisional={provisional} official={displayedOfficialResult}
            officialStatus={officialStatus} officialError={officialError}
            revisionId={revisionId}
            canRun={editor.canEdit && connectionStatus === 'connected' && secondsLeft > 0}
            onRunProvisional={() => runProvisional(feedbackBundle?.tests)}
            onRunOfficial={handleOfficialRun}
            officialRunStatus={latestRun?.status}
            canFinalize={connectionStatus === 'connected' && ownPlayer?.isAlive && secondsLeft > 0}
            onFinalize={handleFinalize} isFinalizing={finalizing} />
          {finalizeError && <StatusMessage status="error">{finalizeError}</StatusMessage>}
          <button className={styles.meetingButton} type="button" onClick={handleCallMeeting}
            disabled={meetingBusy || ownMeetingsUsed > 0 || !ownPlayer?.isAlive
              || cooldownSeconds > 0 || secondsLeft === 0 || connectionStatus !== 'connected'}>
            {meetingBusy ? 'Calling meeting…' : ownMeetingsUsed > 0 ? 'Meeting already used'
              : cooldownSeconds > 0 ? `Meeting cooldown · ${formatTime(cooldownSeconds)}`
                : !ownPlayer?.isAlive ? 'Eliminated players cannot call meetings'
                  : connectionStatus !== 'connected' ? 'Reconnect to call a meeting'
                    : 'Call emergency meeting'}
          </button>
          <p className={styles.meetingAvailability}>
            {ownMeetingsUsed > 0 ? 'You have used your one meeting for this match.'
              : cooldownSeconds > 0 ? 'A room-wide cooldown is active.'
                : 'One meeting per player; the call pauses the coding timer for discussion and voting.'}
          </p>
          {meetingError && <StatusMessage status="error">{meetingError}</StatusMessage>}
          <div className={styles.liveHistory}>
            <h2>Revision history</h2>
            <p>Current revision: <code>{revisionId || 'Waiting for server…'}</code></p>
            {historyError && <StatusMessage status="error">{historyError}</StatusMessage>}
            {restoreStatus && <StatusMessage status={restoreStatusKind}>{restoreStatus}</StatusMessage>}
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
            <div><p className={styles.eyebrow}>SHARED WORKSPACE · LIVE</p><h2 id="live-editor-title">{isCpp ? 'challenge.cpp' : 'challenge.py'}</h2></div>
            <span className={styles.languageBadge}>{isCpp ? 'C++20' : 'PYTHON'}</span>
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
              language={session.challenge.language} label={isCpp ? 'Shared C++ code' : 'Shared Python code'}
              canEdit={editor.canEdit && connectionStatus === 'connected' && secondsLeft > 0}
              preferAccessibleEditor={accessibleMode} />}
          </Suspense>
          <div className={styles.editorFooter}>
            <span><span className={styles.statusDot} aria-hidden="true" /> {editor.status === 'synced' ? 'Shared document synced' : 'Waiting for shared document'}</span>
            <span>{collaborators.length} collaborator{collaborators.length === 1 ? '' : 's'} online</span>
          </div>
          {collaborators.length > 0 && <p className={styles.collaborators}>Editing with {collaborators.join(', ')}</p>}
        </section>
        <aside className={styles.sideColumn} aria-label="Room players and chat">
          <section className={styles.playersPanel}>
            <p className={styles.eyebrow}>IN THIS ROOM</p><h2>Players</h2>
            <ul className={styles.playerList}>{room.players.map((player) =>
              <PlayerCard className={styles.playerRow} key={player.id} player={player} spriteState="coding" variant="compact" />)}</ul>
          </section>
          <ChatPanel
            className={styles.liveChat}
            messages={chatMessages}
            onSendMessage={onSendChat}
            isLive
            maxLength={500}
            title="Room chat"
            emptyMessage="No room messages yet. Start the conversation."
            messageStatus={connectionStatus === 'connected' ? 'Messages are saved by the room server.' : 'Reconnecting before chat can send…'}
            disabled={!canSendChat}
            disabledMessage={connectionStatus !== 'connected'
              ? 'Reconnect before sending a message.'
              : !ownPlayer?.isAlive ? 'Eliminated players can read chat but cannot send.' : ''}
          />
        </aside>
      </div>
      {secondsLeft === 0 && <div className={styles.timeUpBanner} role="status">Round deadline reached. Waiting for server result…</div>}
    </main>
  );
}
