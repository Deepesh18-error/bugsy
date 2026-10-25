import { useState } from 'react';
import Button from '../components/Button.jsx';
import Panel from '../components/Panel.jsx';
import PlayerCard from '../components/PlayerCard.jsx';
import StatusMessage from '../components/StatusMessage.jsx';
import ChatPanel from '../components/ChatPanel.jsx';
import { PREVIEW_MATCH } from '../data/mockMatch.js';
import styles from '../styles/LobbyScreen.module.css';

export default function LobbyScreen({
  room, message, messageStatus = 'info', isLive = false, isBusy = false,
  connectionStatus = 'idle', connectionError = '', hasSequenceGap = false,
  lastEvent = null,
  chatMessages = [], onSendChat, canSendChat = false,
  onBack, onStart, onToggleReady,
}) {
  const [copyMessage, setCopyMessage] = useState('');
  const currentPlayer = room.players.find((player) => player.id === room.currentPlayerId);
  const isHost = currentPlayer?.isHost ?? false;
  const connectedPlayers = room.players.filter((player) => player.isConnected !== false);
  const readyCount = connectedPlayers.filter((player) => player.ready).length;
  const enoughPlayers = connectedPlayers.length >= PREVIEW_MATCH.minimumPlayers
    && connectedPlayers.length <= room.capacity;
  const everyoneReady = connectedPlayers.length > 0 && readyCount === connectedPlayers.length;
  const isLobbyPhase = !isLive || room.phase === 'lobby';
  const isConnected = !isLive || (connectionStatus === 'connected' && currentPlayer?.isConnected !== false);
  const canStart = isLobbyPhase && isHost && enoughPlayers && everyoneReady && isConnected;
  const host = room.players.find((player) => player.isHost);
  const lifecycleNotice = lastEvent?.name === 'PlayerDeparted'
    ? 'A player left the room. Their seat is available for someone else.'
    : lastEvent?.name === 'HostTransferred'
      ? 'Host rights changed. The player marked HOST can start when everyone is ready.'
      : '';
  const connectionText = {
    idle: 'Waiting to connect to the room…',
    connecting: 'Connecting to the room…',
    connected: hasSequenceGap ? 'Catching up with room updates…' : 'Connected. Room updates arrive automatically.',
    reconnecting: 'Reconnecting to the room… Your actions will be available again shortly.',
    error: connectionError || 'Room connection is unavailable.',
  }[connectionStatus] || 'Connecting to the room…';

  let startHint = 'All players are ready. The host can start the match.';
  if (!isConnected) startHint = 'Reconnect to the room before changing readiness or starting.';
  else if (!isHost) startHint = `Waiting for ${host?.name ?? 'the host'} to start the match.`;
  else if (!enoughPlayers) startHint = `A match needs ${PREVIEW_MATCH.minimumPlayers}–${room.capacity} connected players. ${connectedPlayers.length} connected now.`;
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
          <Button className={styles.backButton} disabled={isBusy} onClick={onBack} variant="unstyled">
            <span aria-hidden="true">←</span> {isLive ? 'Leave room' : 'Back to start'}
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
              {isLive
                ? `Share the code with your friends. ${host?.name ?? 'The host'} can start when at least ${PREVIEW_MATCH.minimumPlayers} players are connected and all connected players are ready.`
                : 'Share the room code with your friends. Once everyone is ready, the host can kick off the investigation.'}
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
              <p>{isLive
                ? 'The server owns the lineup and ready states. Disconnected players keep their seat during reconnect grace, but do not count toward match start.'
                : 'This is a local prototype. The other players shown here are sample profiles, not connected people.'}</p>
            </div>
          </div>

          <Panel variant="unstyled" className={styles.lobbyCard} aria-labelledby="players-title">
            <div className={styles.cardHeader}>
              <div><p className={styles.cardEyebrow}>THE LINEUP</p><h2 id="players-title">Players</h2></div>
              <span className={styles.playerCount}>{room.players.length}<span> / {room.capacity}</span></span>
            </div>

            {isLive && <StatusMessage className={styles.connectionStatus} status={connectionStatus === 'error' ? 'error' : connectionStatus === 'connected' && !hasSequenceGap ? 'success' : 'reconnecting'}>
              {connectionText}
            </StatusMessage>}
            {isLive && lifecycleNotice && (
              <StatusMessage className={styles.connectionStatus} status="info">
                {lifecycleNotice}
              </StatusMessage>
            )}

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

            {!isLive && <details className={styles.connectionPreview}>
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
            </details>}

            <div className={styles.readySummary}>
              <span className={styles.readyMeter} aria-hidden="true">
                <span style={{ width: `${connectedPlayers.length ? (readyCount / connectedPlayers.length) * 100 : 0}%` }} />
              </span>
              <span>{readyCount} of {connectedPlayers.length} connected ready</span>
            </div>

            <div className={styles.actions}>
              <Button
                className={`${styles.readyButton} ${currentPlayer?.ready ? styles.readyButtonActive : ''}`}
                disabled={isBusy || !isConnected || !isLobbyPhase || !currentPlayer}
                onClick={onToggleReady}
                aria-pressed={Boolean(currentPlayer?.ready)}
                variant="unstyled"
              >
                {currentPlayer?.ready ? '✓ You’re ready' : 'I’m ready'}
              </Button>
              <Button className={styles.startButton} disabled={!canStart || isBusy || !isConnected} onClick={onStart} variant="unstyled">
                Start match <span aria-hidden="true">→</span>
              </Button>
            </div>
            <StatusMessage as="p" className={styles.startHint} icon="" status="info">
              {startHint}
            </StatusMessage>
            {message && <StatusMessage as="p" className={styles.startHint} status={messageStatus}>
              {message}
            </StatusMessage>}
            {isLive && <ChatPanel
              className={styles.lobbyChat}
              messages={chatMessages}
              onSendMessage={onSendChat}
              isLive
              maxLength={500}
              title="Room chat"
              emptyMessage="No messages yet. Say hello while everyone joins."
              messageStatus={connectionStatus === 'connected'
                ? 'Chat is saved and shared with this room.' : 'Reconnect before sending a message.'}
              disabled={!canSendChat}
              disabledMessage={connectionStatus !== 'connected'
                ? 'Reconnect before sending a message.'
                : !currentPlayer?.isAlive ? 'Eliminated players cannot send messages.' : ''}
            />}
          </Panel>
        </section>

        <footer className={styles.footer}>
          <span>BUILD TOGETHER. TRUST CAREFULLY.</span><span>CODEMAFIA · {isLive ? 'LIVE ROOM' : 'LOCAL PREVIEW'}</span>
        </footer>
      </div>
    </main>
  );
}
