import { useEffect, useState } from 'react';
import ChatPanel from '../components/ChatPanel.jsx';
import PlayerCard from '../components/PlayerCard.jsx';
import { INITIAL_DISCUSSION, PREVIEW_MATCH } from '../data/mockMatch.js';
import styles from '../styles/MeetingScreen.module.css';

const DISCUSSION_SECONDS = PREVIEW_MATCH.discussionSeconds;

function formatTime(seconds) {
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `${String(minutes).padStart(2, '0')}:${String(remainingSeconds).padStart(2, '0')}`;
}

export default function MeetingScreen({ room, categoryName, roundNumber, onProceedToVote,
  isLive = false, deadlineAt = null, chatMessages = [], onSendMessage,
  canSendChat = false, connectionStatus = 'connected' }) {
  const [secondsLeft, setSecondsLeft] = useState(DISCUSSION_SECONDS);
  const [messages, setMessages] = useState(INITIAL_DISCUSSION);

  useEffect(() => {
    if (isLive) {
      const update = () => setSecondsLeft(deadlineAt
        ? Math.max(0, Math.ceil((Date.parse(deadlineAt) - Date.now()) / 1000)) : 0);
      update();
      const intervalId = window.setInterval(update, 1000);
      return () => window.clearInterval(intervalId);
    }
    if (secondsLeft === 0) return undefined;

    const intervalId = window.setInterval(() => {
      setSecondsLeft((currentSeconds) => Math.max(0, currentSeconds - 1));
    }, 1000);

    return () => window.clearInterval(intervalId);
  }, [secondsLeft, isLive, deadlineAt]);

  function handleSendMessage(text) {
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
  }

  const timerIsLow = secondsLeft <= 10;

  return (
    <main className={styles.page}>
      <div className={styles.frame}>
        <header className={styles.topbar}>
          <a className={styles.brand} href="#meeting">
            <span className={styles.brandMark} aria-hidden="true">CM</span>
            <span>BUGSY</span>
          </a>
          <div className={styles.roomMeta}>
            <span>ROOM</span>
            <strong>{room.code}</strong>
          </div>
        </header>

        <section className={styles.content} id="meeting">
          <div className={styles.heading}>
            <p className={styles.eyebrow}><span aria-hidden="true">!</span> EMERGENCY MEETING · ROUND {roundNumber}</p>
            <h1>EMERGENCY<br /><span>MEETING</span></h1>
            <p className={styles.intro}>Discuss the code. Then vote.</p>
          </div>

          {room.players.find((player) => player.id === room.currentPlayerId)?.isAlive === false &&
            <p className={styles.spectatorNotice} role="status">SPECTATOR MODE · Follow the discussion. Ejected players cannot send messages or vote.</p>}
          <div className={styles.meetingGrid}>
            <section className={styles.discussionPanel} aria-labelledby="discussion-title">
              <div className={styles.panelHeader}>
                <div>
                  <p className={styles.panelEyebrow}>OPEN DISCUSSION</p>
                  <h2 id="discussion-title">Crew channel</h2>
                </div>
                <div className={`${styles.timer} ${timerIsLow ? styles.timerLow : ''}`} role="timer" aria-live="off" aria-label={`${formatTime(secondsLeft)} discussion time remaining`}>
                  <span>DISCUSSION</span>
                  <strong>{formatTime(secondsLeft)}</strong>
                </div>
                <span className="srOnly" role="status">
                  {secondsLeft > 0 && secondsLeft <= 10 ? '10 seconds or less remain in discussion.' : ''}
                </span>
              </div>

              <div className={styles.contextCard}>
                <span className={styles.contextIcon} aria-hidden="true">⌁</span>
                <div>
                  <p className={styles.panelEyebrow}>CURRENT ROUND</p>
                  <strong>{categoryName}</strong>
                </div>
              </div>

              <ChatPanel
                className={styles.discussionChat}
                eyebrow="DISCUSSION THREAD"
                emptyMessage="No discussion messages yet. Share an observation."
                localLabel={isLive ? 'Messages seen during this connection.'
                  : 'Local preview discussion · messages are not sent to other players.'}
                messages={isLive ? chatMessages : messages}
                onSendMessage={isLive ? onSendMessage : handleSendMessage}
                placeholder="Share an observation..."
                title="Discussion messages"
                isLive={isLive}
                maxLength={isLive ? 500 : 180}
                messageStatus={isLive && connectionStatus !== 'connected' ? 'Reconnecting to discussion…' : ''}
                disabled={isLive && !canSendChat}
                disabledMessage={isLive && connectionStatus !== 'connected'
                  ? 'Reconnect before sending a discussion message.'
                  : isLive && !canSendChat ? 'Eliminated players can read discussion but cannot send.' : ''}
              />
            </section>

            <aside className={styles.rosterPanel} aria-labelledby="roster-title">
              <div className={styles.panelHeader}>
                <div>
                  <p className={styles.panelEyebrow}>ROOM ROSTER</p>
                  <h2 id="roster-title">Crew present</h2>
                </div>
                <span className={styles.playerCount}>{room.players.length}</span>
              </div>
              <ul className={styles.playerList}>
                {room.players.map((player) => (
                  <PlayerCard className={styles.playerRow} key={player.id} player={player} spriteState="meeting" variant="compact" />
                ))}
              </ul>

              <div className={styles.guideline}><span aria-hidden="true">◎</span><p>Look for evidence in edits and tests.</p></div>

              {isLive ? <p className={styles.previewNote} role="status">
                Voting opens automatically when the server discussion deadline arrives.
              </p> : <button className={styles.resumeButton} onClick={onProceedToVote} type="button">
                End discussion &amp; open vote <span aria-hidden="true">→</span>
              </button>}
              <p className={styles.previewNote}>
                {isLive ? 'The shared editor is paused during the meeting.'
                  : 'Voting is the next phase. The local preview simulates the other players’ ballots when you submit yours.'}
              </p>
            </aside>
          </div>

          {secondsLeft === 0 && (
            <p className={styles.timeUp} role="status">
              {isLive ? 'Discussion ended. Waiting for the server to open voting…'
                : 'Discussion timer ended. Continue when the group is ready to vote.'}
            </p>
          )}
        </section>

        <footer className={styles.footer}>
          <span>DISCUSS THE EVIDENCE. DO NOT ASSUME INTENT.</span>
          <span>BUGSY · {isLive ? 'LIVE ROOM' : 'LOCAL PREVIEW'}</span>
        </footer>
      </div>
    </main>
  );
}
