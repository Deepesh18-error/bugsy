import { useEffect, useState } from 'react';
import ChatPanel from '../components/ChatPanel.jsx';
import PlayerCard from '../components/PlayerCard.jsx';
import StatusMessage from '../components/StatusMessage.jsx';
import styles from '../styles/ArenaScreen.module.css';

const ROUND_SECONDS = 60;

const CHALLENGES = {
  'data-structures': {
    title: 'Repair the task queue',
    summary: 'Fix the queue so items are added and removed in first-in, first-out order.',
    starterCode: `class TaskQueue:\n    def __init__(self):\n        self.items = []\n\n    def enqueue(self, item):\n        # TODO: add item to the back of the queue\n        pass\n\n    def dequeue(self):\n        # TODO: return and remove the oldest item\n        pass`,
    testNames: ['New items are added', 'Oldest item leaves first', 'Empty queue is handled'],
  },
  'object-oriented': {
    title: 'Repair the counter',
    summary: 'Correct the counter methods while preserving the object’s change history.',
    starterCode: `class Counter:\n    def __init__(self):\n        self.count = 0\n        self.history = []\n\n    def increment(self):\n        self.count += 1\n        self.history.append("inc")\n\n    def decrement(self):\n        # TODO: subtract one and record the change\n        self.count -= 2\n        self.history.append("dec")\n\n    def reset(self):\n        # TODO: reset the count to zero\n        pass`,
    testNames: ['Increment changes count', 'Decrement changes count by one', 'Reset returns to zero'],
  },
  security: {
    title: 'Repair the input validator',
    summary: 'Reject unsafe input consistently before it reaches the application.',
    starterCode: `def is_valid_username(value):\n    # TODO: reject empty values and values longer than 24 chars\n    if value is None:\n        return True\n\n    # TODO: allow only letters, digits, and underscores\n    return True`,
    testNames: ['Empty input is rejected', 'Length limit is enforced', 'Unsafe characters are rejected'],
  },
  frontend: {
    title: 'Repair the form state',
    summary: 'Keep the submit state accurate when a user edits and submits a form.',
    starterCode: `def submit_form(values):\n    # TODO: reject a form with a blank email\n    email = values.get("email", "")\n\n    if email:\n        return {"submitted": True, "email": email}\n\n    # TODO: report invalid form state\n    return {"submitted": True, "email": email}`, 
    testNames: ['Valid email can submit', 'Blank email is rejected', 'Submitted email is preserved'],
  },
  backend: {
    title: 'Repair the response builder',
    summary: 'Return a predictable API response and handle missing records safely.',
    starterCode: `def build_user_response(user):\n    # TODO: return None when the user does not exist\n    if user is None:\n        return {}\n\n    return {\n        "id": user.get("id"),\n        # TODO: include the display name from the record\n        "name": user.get("username"),\n    }`,
    testNames: ['Missing user is handled', 'Response contains an ID', 'Display name uses the right field'],
  },
};

const INITIAL_CHAT = [
  { id: 'chat-1', name: 'Maya', tone: 'violet', text: 'I’ll inspect the failing method first.' },
  { id: 'chat-2', name: 'Jules', tone: 'mint', text: 'I see a TODO near the reset logic.' },
];

function formatTime(seconds) {
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `${String(minutes).padStart(2, '0')}:${String(remainingSeconds).padStart(2, '0')}`;
}

export default function ArenaScreen({
  room,
  role,
  categoryId,
  categoryName,
  roundNumber,
  totalRounds,
  isPaused = false,
  meetingAvailable = true,
  onCallMeeting,
  onRoundTimeout,
}) {
  const challenge = CHALLENGES[categoryId] ?? CHALLENGES['object-oriented'];
  const previewResults = challenge.testNames.map((name, index) => ({
    name,
    passed: index < challenge.testNames.length - 1,
  }));
  const [secondsLeft, setSecondsLeft] = useState(ROUND_SECONDS);
  const [code, setCode] = useState(challenge.starterCode);
  const [hasRunPreview, setHasRunPreview] = useState(false);
  const [isResultStale, setIsResultStale] = useState(false);
  const [chatMessages, setChatMessages] = useState(INITIAL_CHAT);

  useEffect(() => {
    if (isPaused || secondsLeft === 0) return undefined;

    const intervalId = window.setInterval(() => {
      setSecondsLeft((currentSeconds) => Math.max(0, currentSeconds - 1));
    }, 1000);

    return () => window.clearInterval(intervalId);
  }, [secondsLeft, isPaused]);

  useEffect(() => {
    if (secondsLeft === 0 && !isPaused) onRoundTimeout?.();
  }, [secondsLeft, isPaused, onRoundTimeout]);

  function handleCodeChange(event) {
    setCode(event.target.value);
    if (hasRunPreview) setIsResultStale(true);
  }

  function handlePreviewTests() {
    if (secondsLeft === 0) return;
    setHasRunPreview(true);
    setIsResultStale(false);
  }

  function handleSendChat(text) {
    const currentPlayer = room.players.find((player) => player.id === room.currentPlayerId);
    setChatMessages((messages) => [
      ...messages,
      {
        id: `local-${Date.now()}`,
        name: currentPlayer?.name ?? 'You',
        tone: currentPlayer?.tone ?? 'coral',
        text,
        isYou: true,
      },
    ]);
  }

  const passedCount = previewResults.filter((result) => result.passed).length;
  const timerIsLow = secondsLeft <= 15;

  return (
    <main className={styles.page}>
      <header className={styles.topbar}>
        <a className={styles.brand} href="#arena" aria-label="CodeMafia arena">
          <span className={styles.brandMark} aria-hidden="true">CM</span>
          <span>codemafia</span>
        </a>
        <div className={styles.roundMeta}>
          <span>ROUND {roundNumber}/{totalRounds}</span>
          <span className={styles.metaDivider} aria-hidden="true">·</span>
          <span>{categoryName}</span>
        </div>
        <div className={`${styles.timer} ${timerIsLow ? styles.timerLow : ''}`} aria-live="off" aria-label={`${formatTime(secondsLeft)} remaining`}>
          <span className={styles.timerLabel}>TIME LEFT</span>
          <strong>{formatTime(secondsLeft)}</strong>
        </div>
        <div className={styles.roomCode}><span>ROOM</span><strong>{room.code}</strong></div>
      </header>

      <div className={styles.layout} id="arena">
        <section className={styles.challengePanel} aria-labelledby="challenge-title">
          <div className={styles.panelHeading}>
            <div>
              <p className={styles.eyebrow}>THE CHALLENGE</p>
              <h1 id="challenge-title">{challenge.title}</h1>
            </div>
            <span className={styles.roundBadge}>ROUND {roundNumber}</span>
          </div>
          <p className={styles.challengeSummary}>{challenge.summary}</p>

          <section className={styles.testsSection} aria-labelledby="tests-title">
            <div className={styles.sectionHeading}>
              <div>
                <p className={styles.eyebrow}>QUALITY CHECKS</p>
                <h2 id="tests-title">Test cases</h2>
              </div>
              <span className={styles.testCount}>
                {hasRunPreview ? `${passedCount}/${previewResults.length}` : `0/${challenge.testNames.length}`}
              </span>
            </div>

            {!hasRunPreview ? (
              <ul className={styles.testList}>
                {challenge.testNames.map((testName) => (
                  <li className={styles.testItem} key={testName}>
                    <span className={styles.testPending} aria-hidden="true">○</span>
                    <span>{testName}</span>
                    <span className={styles.pendingLabel}>NOT RUN</span>
                  </li>
                ))}
              </ul>
            ) : (
              <>
                {isResultStale && (
                  <StatusMessage as="p" className={styles.staleNotice} status="warning">
                    Code changed after this preview. These sample results are stale.
                  </StatusMessage>
                )}
                <ul className={styles.testList}>
                  {previewResults.map((result) => (
                    <li className={`${styles.testItem} ${result.passed ? styles.testPassed : styles.testFailed}`} key={result.name}>
                      <span aria-hidden="true">{result.passed ? '✓' : '!'}</span>
                      <span>{result.name}</span>
                      <span className={styles.pendingLabel}>{result.passed ? 'PASS' : 'FAIL'}</span>
                    </li>
                  ))}
                </ul>
              </>
            )}
            <button className={styles.runButton} onClick={handlePreviewTests} type="button" disabled={secondsLeft === 0}>
              {hasRunPreview ? 'Run sample again' : 'Run sample tests'}
              <span aria-hidden="true">↗</span>
            </button>
            <p className={styles.mockNote}>Preview only: this button does not execute your Python code.</p>
          </section>

          <section className={styles.objectiveCard} aria-label="Your role objective">
            <span className={`${styles.roleDot} ${role === 'impostor' ? styles.impostorDot : ''}`} aria-hidden="true" />
            <div>
              <p className={styles.eyebrow}>YOUR ROLE</p>
              <strong>{role === 'impostor' ? 'Impostor' : 'Civilian'}</strong>
            </div>
            <p>{role === 'impostor' ? 'Blend in while steering the code off course.' : 'Work together to repair the challenge.'}</p>
          </section>
          <button
            className={styles.meetingButton}
            onClick={onCallMeeting}
            type="button"
            disabled={!meetingAvailable || secondsLeft === 0}
          >
            <span aria-hidden="true">!</span>
            {meetingAvailable ? 'Call emergency meeting' : 'Meeting already used'}
          </button>
          <p className={styles.mockNote}>One local preview meeting per player each match.</p>
        </section>

        <section className={styles.editorPanel} aria-labelledby="editor-title">
          <div className={styles.editorHeader}>
            <div>
              <p className={styles.eyebrow}>SHARED WORKSPACE · PREVIEW</p>
              <h2 id="editor-title">challenge.py</h2>
            </div>
            <span className={styles.languageBadge}>PYTHON</span>
          </div>
          <label className={styles.editorLabel} htmlFor="code-editor">
            Code editor placeholder. Edit the sample text; it is not shared with other players.
          </label>
          <textarea
            className={styles.codeEditor}
            id="code-editor"
            value={code}
            onChange={handleCodeChange}
            spellCheck="false"
            aria-describedby="editor-help"
          />
          <div className={styles.editorFooter} id="editor-help">
            <span><span className={styles.statusDot} aria-hidden="true" /> Local draft</span>
            <span>{code.split('\n').length} lines</span>
          </div>
          <p className={styles.editorNote}>Collaborative editing and real Python execution arrive in later phases.</p>
        </section>

        <aside className={styles.sideColumn} aria-label="Players and chat">
          <section className={styles.playersPanel} aria-labelledby="players-title">
            <div className={styles.sectionHeading}>
              <div>
                <p className={styles.eyebrow}>IN THIS ROOM</p>
                <h2 id="players-title">Players</h2>
              </div>
              <span className={styles.testCount}>{room.players.length}/{room.capacity}</span>
            </div>
            <ul className={styles.playerList}>
              {room.players.map((player) => (
                <PlayerCard className={styles.playerRow} key={player.id} player={player} variant="compact" />
              ))}
            </ul>
          </section>

          <ChatPanel
            className={styles.chatPanel}
            emptyMessage="No messages yet. Start the team conversation."
            localLabel="Messages stay in this browser preview."
            messages={chatMessages}
            onSendMessage={handleSendChat}
            placeholder="Message your team..."
          />
        </aside>
      </div>

      {secondsLeft === 0 && (
        <div className={styles.timeUpBanner} role="status">
          Preview timer ended. Opening the round result...
        </div>
      )}
    </main>
  );
}
