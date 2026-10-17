import { useState } from 'react';
import Button from '../components/Button.jsx';
import Panel from '../components/Panel.jsx';
import PlayerCard from '../components/PlayerCard.jsx';
import StatusMessage from '../components/StatusMessage.jsx';
import { PREVIEW_MATCH } from '../data/mockMatch.js';
import styles from '../styles/LobbyScreen.module.css';

export default function LobbyScreen({ room, message, onBack, onStart, onToggleReady }) {
  const [copyMessage, setCopyMessage] = useState('');
  const currentPlayer = room.players.find((player) => player.id === room.currentPlayerId);
  const isHost = currentPlayer?.isHost ?? false;
  const readyCount = room.players.filter((player) => player.ready).length;
  const enoughPlayers = room.players.length >= PREVIEW_MATCH.minimumPlayers
    && room.players.length <= room.capacity;
  const everyoneReady = readyCount === room.players.length;
  const canStart = isHost && enoughPlayers && everyoneReady;

  let startHint = 'All players are ready. The host can start the match.';
  if (!isHost) startHint = 'Waiting for the host to start the match.';
  else if (!enoughPlayers) startHint = `A match needs ${PREVIEW_MATCH.minimumPlayers}–${room.capacity} players.`;
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
          <Button className={styles.backButton} onClick={onBack} variant="unstyled">
            <span aria-hidden="true">←</span> Back to start
          </Button>
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
              <Button aria-label="Copy room code" className={styles.copyButton} onClick={handleCopyCode} variant="unstyled">
                <span aria-hidden="true">▢</span><span>Copy</span>
              </Button>
            </div>
            <StatusMessage as="p" className={styles.copyMessage} icon="" status={copyMessage.includes('unavailable') ? 'warning' : copyMessage ? 'success' : 'info'}>
              {copyMessage || 'Friends can enter this code on the welcome screen.'}
            </StatusMessage>

            <div className={styles.lobbyNote}>
              <span className={styles.noteIcon} aria-hidden="true">i</span>
              <p>This is a local prototype. The other players shown here are sample profiles, not connected people.</p>
            </div>
          </div>

          <Panel variant="unstyled" className={styles.lobbyCard} aria-labelledby="players-title">
            <div className={styles.cardHeader}>
              <div><p className={styles.cardEyebrow}>THE LINEUP</p><h2 id="players-title">Players</h2></div>
              <span className={styles.playerCount}>{room.players.length}<span> / {room.capacity}</span></span>
            </div>

            <ul aria-label="Players in this room" className={styles.playerList}>
              {room.players.map((player) => (
                <PlayerCard className={styles.playerRow} key={player.id} player={player} variant="lobby" />
              ))}
              {room.players.length < room.capacity && (
                <li className={styles.openSlot}>
                  <span className={styles.openSlotPlus} aria-hidden="true">+</span>
                  <span>{room.capacity - room.players.length} open seat{room.capacity - room.players.length === 1 ? '' : 's'}</span>
                </li>
              )}
            </ul>

            <details className={styles.connectionPreview}>
              <summary>Preview reconnecting and disconnected states</summary>
              <ul aria-label="Connection state example" className={styles.playerList}>
                <PlayerCard
                  player={{ id: 'connection-example', name: 'Sample teammate', tone: 'gold', isConnected: false, isAlive: true }}
                  variant="compact"
                />
              </ul>
              <StatusMessage status="reconnecting">
                Reconnecting to the room… This is a simulated connection state.
              </StatusMessage>
            </details>

            <div className={styles.readySummary}>
              <span className={styles.readyMeter} aria-hidden="true">
                <span style={{ width: `${(readyCount / room.players.length) * 100}%` }} />
              </span>
              <span>{readyCount} of {room.players.length} ready</span>
            </div>

            <div className={styles.actions}>
              <Button
                className={`${styles.readyButton} ${currentPlayer?.ready ? styles.readyButtonActive : ''}`}
                onClick={onToggleReady}
                aria-pressed={Boolean(currentPlayer?.ready)}
                variant="unstyled"
              >
                {currentPlayer?.ready ? '✓ You’re ready' : 'I’m ready'}
              </Button>
              <Button className={styles.startButton} disabled={!canStart} onClick={onStart} variant="unstyled">
                Start match <span aria-hidden="true">→</span>
              </Button>
            </div>
            <StatusMessage as="p" className={styles.startHint} icon="" status={message ? 'success' : 'info'}>{message || startHint}</StatusMessage>
          </Panel>
        </section>

        <footer className={styles.footer}>
          <span>BUILD TOGETHER. TRUST CAREFULLY.</span><span>CODEMAFIA · LOCAL PREVIEW</span>
        </footer>
      </div>
    </main>
  );
}
