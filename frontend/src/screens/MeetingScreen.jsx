import { useEffect, useState } from 'react';
import styles from '../styles/MeetingScreen.module.css';

const DISCUSSION_SECONDS = 30;
const MAX_MESSAGE_LENGTH = 180;

const INITIAL_DISCUSSION = [
  { id: 'discussion-1', name: 'Maya', tone: 'violet', text: 'What changed right before the test failed?' },
  { id: 'discussion-2', name: 'Jules', tone: 'mint', text: 'Let’s compare the edit history before we assume intent.' },
];

function formatTime(seconds) {
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `${String(minutes).padStart(2, '0')}:${String(remainingSeconds).padStart(2, '0')}`;
}

export default function MeetingScreen({ room, categoryName, roundNumber, onResumeCoding }) {
  const [secondsLeft, setSecondsLeft] = useState(DISCUSSION_SECONDS);
  const [messages, setMessages] = useState(INITIAL_DISCUSSION);
  const [draft, setDraft] = useState('');
  const [notice, setNotice] = useState('');

  useEffect(() => {
    if (secondsLeft === 0) return undefined;

    const intervalId = window.setInterval(() => {
      setSecondsLeft((currentSeconds) => Math.max(0, currentSeconds - 1));
    }, 1000);

    return () => window.clearInterval(intervalId);
  }, [secondsLeft]);

  function handleSendMessage(event) {
    event.preventDefault();
    const text = draft.trim();

    if (!text) {
      setNotice('Write a message before sending.');
      return;
    }

    const currentPlayer = room.players.find((player) => player.id === room.currentPlayerId);
    setMessages((currentMessages) => [
      ...currentMessages,
      {
        id: `meeting-${Date.now()}`,
        name: currentPlayer?.name ?? 'You',
        tone: currentPlayer?.tone ?? 'coral',
        text,
        isYou: true,
      },
    ]);
    setDraft('');
    setNotice('Message added to this local meeting preview.');
  }

  const timerIsLow = secondsLeft <= 10;

  return (
    <main className={styles.page}>
      <div className={styles.frame}>
        <header className={styles.topbar}>
          <a className={styles.brand} href="#meeting" aria-label="CodeMafia meeting">
            <span className={styles.brandMark} aria-hidden="true">CM</span>
            <span>codemafia</span>
          </a>
          <div className={styles.roomMeta}>
            <span>ROOM</span>
            <strong>{room.code}</strong>
          </div>
        </header>

        <section className={styles.content} id="meeting">
          <div className={styles.heading}>
            <p className={styles.eyebrow}><span aria-hidden="true">!</span> EMERGENCY MEETING · ROUND {roundNumber}</p>
            <h1>Pause the code.<br /><span>Compare what you saw.</span></h1>
            <p className={styles.intro}>
              Discuss the edits and test behavior together. A failing test can come from an honest mistake; evidence is not proof of intent.
            </p>
          </div>

          <div className={styles.meetingGrid}>
            <section className={styles.discussionPanel} aria-labelledby="discussion-title">
              <div className={styles.panelHeader}>
                <div>
                  <p className={styles.panelEyebrow}>OPEN DISCUSSION</p>
                  <h2 id="discussion-title">What happened?</h2>
                </div>
                <div className={`${styles.timer} ${timerIsLow ? styles.timerLow : ''}`} aria-label={`${formatTime(secondsLeft)} discussion time remaining`}>
                  <span>DISCUSSION</span>
                  <strong>{formatTime(secondsLeft)}</strong>
                </div>
              </div>

              <div className={styles.contextCard}>
                <span className={styles.contextIcon} aria-hidden="true">⌁</span>
                <div>
                  <p className={styles.panelEyebrow}>CURRENT ROUND</p>
                  <strong>{categoryName}</strong>
                  <p>Players can share observations before the group moves on.</p>
                </div>
              </div>

              <ol className={styles.messages} aria-live="polite" aria-relevant="additions">
                {messages.map((message) => (
                  <li className={styles.message} key={message.id}>
                    <span className={`${styles.messageAvatar} ${styles[message.tone] ?? ''}`} aria-hidden="true">
                      {message.name.slice(0, 1).toUpperCase()}
                    </span>
                    <div className={styles.messageBody}>
                      <strong className={styles[message.tone] ?? ''}>
                        {message.name}{message.isYou ? ' · you' : ''}
                      </strong>
                      <p>{message.text}</p>
                    </div>
                  </li>
                ))}
              </ol>

              <form className={styles.messageForm} onSubmit={handleSendMessage}>
                <label className={styles.srOnly} htmlFor="meeting-message">Add to the discussion</label>
                <input
                  id="meeting-message"
                  maxLength={MAX_MESSAGE_LENGTH}
                  onChange={(event) => {
                    setDraft(event.target.value);
                    setNotice('');
                  }}
                  placeholder="Share an observation..."
                  value={draft}
                />
                <button type="submit" aria-label="Send discussion message">Send</button>
              </form>
              <p className={styles.notice} role="status">{notice || 'Local preview discussion · messages are not sent to other players.'}</p>
            </section>

            <aside className={styles.rosterPanel} aria-labelledby="roster-title">
              <div className={styles.panelHeader}>
                <div>
                  <p className={styles.panelEyebrow}>ROOM ROSTER</p>
                  <h2 id="roster-title">Players here</h2>
                </div>
                <span className={styles.playerCount}>{room.players.length}</span>
              </div>
              <ul className={styles.playerList}>
                {room.players.map((player) => (
                  <li className={styles.playerRow} key={player.id}>
                    <span className={`${styles.playerAvatar} ${styles[player.tone] ?? ''}`} aria-hidden="true">
                      {player.name.slice(0, 1).toUpperCase()}
                    </span>
                    <span className={styles.playerName}>
                      {player.name}{player.isYou ? ' (you)' : ''}
                    </span>
                    <span className={player.isYou ? styles.youTag : styles.presentTag}>
                      {player.isYou ? 'YOU' : 'PRESENT'}
                    </span>
                  </li>
                ))}
              </ul>

              <div className={styles.guideline}>
                <span aria-hidden="true">◎</span>
                <p>Talk about observable code changes and test results. The meeting does not identify who made a harmful edit.</p>
              </div>

              <button className={styles.resumeButton} onClick={onResumeCoding} type="button">
                End discussion &amp; resume preview <span aria-hidden="true">→</span>
              </button>
              <p className={styles.previewNote}>
                The separate player-voting screen is the next UI step. This preview action resumes coding for now.
              </p>
            </aside>
          </div>

          {secondsLeft === 0 && (
            <p className={styles.timeUp} role="status">
              Discussion timer ended. The local preview is waiting for you to continue.
            </p>
          )}
        </section>

        <footer className={styles.footer}>
          <span>DISCUSS THE EVIDENCE. DO NOT ASSUME INTENT.</span>
          <span>CODEMAFIA · LOCAL PREVIEW</span>
        </footer>
      </div>
    </main>
  );
}
