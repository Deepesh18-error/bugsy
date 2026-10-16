import { useState } from 'react';
import styles from '../styles/LobbyScreen.module.css';

function getInitials(name) {
  return name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('');
}

export default function LobbyScreen({ room, message, onBack, onStart, onToggleReady }) {
  const [copyMessage, setCopyMessage] = useState('');
  const currentPlayer = room.players.find((player) => player.id === room.currentPlayerId);
  const isHost = currentPlayer?.isHost ?? false;
  const readyCount = room.players.filter((player) => player.ready).length;
  const enoughPlayers = room.players.length >= 4 && room.players.length <= room.capacity;
  const everyoneReady = readyCount === room.players.length;
  const canStart = isHost && enoughPlayers && everyoneReady;

  let startHint = 'All players are ready. The host can start the match.';
  if (!isHost) startHint = 'Waiting for the host to start the match.';
  else if (!enoughPlayers) startHint = 'A match needs 4–5 players.';
  else if (!everyoneReady) startHint = 'Everyone needs to be ready before the host starts.';

  async function handleCopyCode() {
    try {
      await navigator.clipboard.writeText(room.code);
      setCopyMessage('Room code copied to your clipboard.');
    } catch {
      setCopyMessage('Clipboard access is unavailable. Select the code to copy it.');
    }
  }

  return (
    <main className={styles.page}>
      <div className={styles.frame}>
        <header className={styles.topbar}>
          <a className={styles.brand} href="#lobby" aria-label="CodeMafia home">
            <span className={styles.brandMark} aria-hidden="true">CM</span><span>codemafia</span>
          </a>
          <button className={styles.backButton} onClick={onBack} type="button">
            <span aria-hidden="true">←</span> Back to start
          </button>
        </header>

        <section className={styles.content} id="lobby">
          <div className={styles.intro}>
            <p className={styles.kicker}>
              <span className={styles.kickerDot} aria-hidden="true" />
              Private room · waiting area
            </p>
            <h1>Your crew is<br /><span>getting together.</span></h1>
            <p className={styles.description}>
              Share the room code with your friends. Once everyone is ready, the
              host can kick off the investigation.
            </p>

            <div className={styles.roomCodeCard}>
              <div>
                <span className={styles.roomCodeLabel}>ROOM CODE</span>
                <p className={styles.roomCode} aria-label={`Room code ${room.code}`}>{room.code}</p>
              </div>
              <button aria-label="Copy room code" className={styles.copyButton} onClick={handleCopyCode} type="button">
                <span aria-hidden="true">▢</span><span>Copy</span>
              </button>
            </div>
            <p aria-live="polite" className={styles.copyMessage}>
              {copyMessage || 'Friends can enter this code on the welcome screen.'}
            </p>

            <div className={styles.lobbyNote}>
              <span className={styles.noteIcon} aria-hidden="true">i</span>
              <p>This is a local prototype. The other players shown here are sample profiles, not connected people.</p>
            </div>
          </div>

          <section className={styles.lobbyCard} aria-labelledby="players-title">
            <div className={styles.cardHeader}>
              <div><p className={styles.cardEyebrow}>THE LINEUP</p><h2 id="players-title">Players</h2></div>
              <span className={styles.playerCount}>{room.players.length}<span> / {room.capacity}</span></span>
            </div>

            <ul aria-label="Players in this room" className={styles.playerList}>
              {room.players.map((player) => (
                <li className={styles.playerRow} key={player.id}>
                  <span className={`${styles.avatar} ${styles[player.tone]}`} aria-hidden="true">
                    {getInitials(player.name)}
                  </span>
                  <span className={styles.playerIdentity}>
                    <span className={styles.playerName}>
                      {player.name}{player.isYou && <span className={styles.youTag}>YOU</span>}
                    </span>
                    <span className={styles.playerMeta}>
                      {player.isHost ? 'Room host' : 'Connected'}{player.isDemo && ' · sample player'}
                    </span>
                  </span>
                  {player.isHost && <span className={styles.hostBadge} aria-label="Host">HOST</span>}
                  <span
                    className={`${styles.readyBadge} ${player.ready ? styles.ready : styles.notReady}`}
                    aria-label={player.ready ? 'Ready' : 'Not ready'}
                  >
                    <span aria-hidden="true">{player.ready ? '✓' : '·'}</span>
                    {player.ready ? 'Ready' : 'Not ready'}
                  </span>
                </li>
              ))}
              {room.players.length < room.capacity && (
                <li className={styles.openSlot}>
                  <span className={styles.openSlotPlus} aria-hidden="true">+</span>
                  <span>{room.capacity - room.players.length} open seat{room.capacity - room.players.length === 1 ? '' : 's'}</span>
                </li>
              )}
            </ul>

            <div className={styles.readySummary}>
              <span className={styles.readyMeter} aria-hidden="true">
                <span style={{ width: `${(readyCount / room.players.length) * 100}%` }} />
              </span>
              <span>{readyCount} of {room.players.length} ready</span>
            </div>

            <div className={styles.actions}>
              <button
                className={`${styles.readyButton} ${currentPlayer?.ready ? styles.readyButtonActive : ''}`}
                onClick={onToggleReady}
                type="button"
                aria-pressed={Boolean(currentPlayer?.ready)}
              >
                {currentPlayer?.ready ? '✓ You’re ready' : 'I’m ready'}
              </button>
              <button className={styles.startButton} disabled={!canStart} onClick={onStart} type="button">
                Start match <span aria-hidden="true">→</span>
              </button>
            </div>
            <p aria-live="polite" className={styles.startHint}>{message || startHint}</p>
          </section>
        </section>

        <footer className={styles.footer}>
          <span>BUILD TOGETHER. TRUST CAREFULLY.</span><span>CODEMAFIA · LOCAL PREVIEW</span>
        </footer>
      </div>
    </main>
  );
}
