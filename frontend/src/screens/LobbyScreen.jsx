import { useEffect, useRef, useState } from 'react';
import Button from '../components/Button.jsx';
import ChatPanel from '../components/ChatPanel.jsx';
import CharacterSprite from '../components/CharacterSprite.jsx';
import StatusMessage from '../components/StatusMessage.jsx';
import { PREVIEW_MATCH } from '../data/mockMatch.js';
import styles from '../styles/LobbyScreen.module.css';

function Satellite() {
  return <svg className={styles.satellite} viewBox="0 0 190 135" role="img" aria-label="Cartoon crew communications satellite">
    <path d="M67 28 35 14 14 42l38 22M122 71l34 22 20-27-39-20" fill="#294355" stroke="#95d9e7" strokeWidth="5" strokeLinejoin="round" />
    <path d="m28 31 27 17m-17-24 27 16m77 28 25 16m-16-26 25 16" stroke="#628da5" strokeWidth="3" />
    <path d="m54 62 31-35 58 45-31 36z" fill="#e8b26e" stroke="#121d2b" strokeWidth="6" strokeLinejoin="round" />
    <path d="m64 62 24-27 45 36-25 27z" fill="#223b4f" stroke="#f3d297" strokeWidth="3" />
    <circle cx="98" cy="65" r="9" fill="#91dce9" /><path d="m111 97 11 13m-38-82-5-17" stroke="#b6d8df" strokeWidth="5" strokeLinecap="round" />
    <path d="M103 8q31 1 42 24M112 0q43 4 58 38" fill="none" stroke="#8fdce6" strokeWidth="3" strokeLinecap="round" className={styles.signalArc} />
  </svg>;
}

export default function LobbyScreen({ room, message, messageStatus = 'info', isLive = false, isBusy = false,
  connectionStatus = 'idle', connectionError = '', hasSequenceGap = false, lastEvent = null,
  chatMessages = [], onSendChat, canSendChat = false, onBack, onStart, onToggleReady }) {
  const [copyMessage, setCopyMessage] = useState('');
  const [leaveOpen, setLeaveOpen] = useState(false);
  const leaveCancelRef = useRef(null);
  useEffect(() => {
    if (!leaveOpen) return undefined;
    leaveCancelRef.current?.querySelector('button')?.focus();
    const onKeyDown = (event) => {
      if (event.key === 'Escape') setLeaveOpen(false);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [leaveOpen]);
  const currentPlayer = room.players.find((player) => player.id === room.currentPlayerId);
  const isHost = currentPlayer?.isHost ?? false;
  const connectedPlayers = room.players.filter((player) => player.isConnected !== false);
  const readyCount = connectedPlayers.filter((player) => player.ready).length;
  const enoughPlayers = connectedPlayers.length >= PREVIEW_MATCH.minimumPlayers && connectedPlayers.length <= room.capacity;
  const everyoneReady = connectedPlayers.length > 0 && readyCount === connectedPlayers.length;
  const isLobbyPhase = !isLive || room.phase === 'lobby';
  const isConnected = !isLive || (connectionStatus === 'connected' && currentPlayer?.isConnected !== false);
  const canStart = isLobbyPhase && isHost && enoughPlayers && everyoneReady && isConnected;
  const host = room.players.find((player) => player.isHost);
  const lifecycleNotice = lastEvent?.name === 'PlayerDeparted' ? 'A player left. Their seat is open again.'
    : lastEvent?.name === 'HostTransferred' ? 'Host changed. The marked player can start the match.' : '';
  const connectionText = {
    idle: 'Connecting to crew channel…', connecting: 'Connecting to crew channel…',
    connected: hasSequenceGap ? 'Syncing crew updates…' : 'Crew channel connected',
    reconnecting: 'Reconnecting to the room…', error: connectionError || 'Room connection is unavailable.',
  }[connectionStatus] || 'Connecting to crew channel…';
  let startHint = 'Crew ready. The host can start.';
  if (!isConnected) startHint = 'Reconnect to the room before changing readiness or starting.';
  else if (!isHost) startHint = `Waiting for ${host?.name ?? 'the host'} to start.`;
  else if (!enoughPlayers) startHint = `Need ${PREVIEW_MATCH.minimumPlayers}–${room.capacity} connected players to start.`;
  else if (!everyoneReady) startHint = 'Everyone connected must be ready.';

  async function handleCopyCode() {
    try { await navigator.clipboard.writeText(room.code); setCopyMessage('Room code copied.'); }
    catch { setCopyMessage('Clipboard unavailable. Select the code to copy it.'); }
  }

  return <main className={styles.page}>
    <div className={styles.stars} aria-hidden="true" /><div className={styles.orbitPlanet} aria-hidden="true" />
    <div className={styles.frame}>
      <header className={styles.topbar}>
        <a className={styles.brand} href="#lobby">BUGSY<span aria-hidden="true">_</span></a>
        <span className={styles.deckLabel}>CREW ASSEMBLY / {isLive ? 'LIVE' : 'PREVIEW'}</span>
        <Button className={styles.backButton} disabled={isBusy} onClick={() => isLive ? setLeaveOpen(true) : onBack()} variant="unstyled">↩ {isLive ? 'Leave room' : 'Back to start'}</Button>
      </header>
      <section className={styles.board} id="lobby" aria-labelledby="lobby-title">
        <div className={styles.boardHeading}>
          <div><p className={styles.eyebrow}>DOCKING BAY / LIVE ROSTER</p><h1 id="lobby-title">Crew assembly</h1></div>
          <div className={styles.roomCodeCard}><div><span className={styles.roomCodeLabel}>ROOM CODE</span><p className={styles.roomCode} aria-label={`Room code ${room.code}`}>{room.code}</p></div>
            <Button aria-label="Copy room code" className={styles.copyButton} onClick={handleCopyCode} variant="unstyled">▢ Copy</Button></div>
        </div>
        {copyMessage && <StatusMessage as="p" className={styles.smallNotice} status={copyMessage.includes('unavailable') ? 'warning' : 'success'}>{copyMessage}</StatusMessage>}
        {isLive && <StatusMessage className={styles.connectionStatus} status={connectionStatus === 'error' ? 'error' : connectionStatus === 'connected' && !hasSequenceGap ? 'success' : 'reconnecting'}>{connectionText}</StatusMessage>}
        {isLive && lifecycleNotice && <StatusMessage className={styles.smallNotice} status="info">{lifecycleNotice}</StatusMessage>}
        <div className={styles.rosterHeader}><h2>YOUR CREW</h2><span>{room.players.length} / {room.capacity} aboard</span></div>
        <ul aria-label="Players in this room" className={styles.playerList}>
          {room.players.map((player, index) => <li className={`${styles.crewBay} ${player.isYou ? styles.crewBayYou : ''} ${player.isConnected === false ? styles.crewBayOffline : ''}`} key={player.id}>
            <span className={styles.bayNumber}>BAY {String(index + 1).padStart(2, '0')}</span>
            <div className={styles.bayCharacter}>{player.avatarId ? <CharacterSprite className={styles.baySprite} decorative id={player.avatarId} state={player.ready ? 'ready' : 'idle'} />
              : <span className={styles.bayInitial} aria-hidden="true">{player.name?.slice(0, 1).toUpperCase() || '?'}</span>}</div>
            <strong className={styles.bayName} title={player.name}>{player.name}</strong>
            <span className={styles.bayRole}>{player.isYou ? 'YOU' : player.isDemo ? 'SAMPLE' : 'CREW'}{player.isHost ? ' · HOST' : ''}</span>
            <span className={`${styles.bayStatus} ${player.ready && player.isConnected !== false ? styles.bayReady : ''}`}>{player.isConnected === false ? 'OFFLINE' : player.ready ? 'READY' : 'STANDBY'}</span>
          </li>)}
          {Array.from({ length: Math.max(0, room.capacity - room.players.length) }, (_, index) => <li className={`${styles.crewBay} ${styles.emptyBay}`} key={`empty-${index}`}>
            <span className={styles.bayNumber}>BAY {String(room.players.length + index + 1).padStart(2, '0')}</span>
            <span className={styles.emptyBayIcon} aria-hidden="true">＋</span><strong className={styles.bayName}>OPEN SEAT</strong><span className={styles.bayRole}>AWAITING CREW</span>
          </li>)}
        </ul>
        <div className={styles.readyControls}>
          <div className={styles.readySummary}><span className={styles.readyMeter} aria-hidden="true"><span style={{ width: `${connectedPlayers.length ? readyCount / connectedPlayers.length * 100 : 0}%` }} /></span><strong>{readyCount} / {connectedPlayers.length} READY</strong></div>
          <div className={styles.actions}>
            <Button className={`${styles.readyButton} ${currentPlayer?.ready ? styles.readyButtonActive : ''}`} disabled={isBusy || !isConnected || !isLobbyPhase || !currentPlayer} onClick={onToggleReady} aria-pressed={Boolean(currentPlayer?.ready)} variant="unstyled">{currentPlayer?.ready ? '✓ You’re ready' : 'I’m ready'}</Button>
            <Button className={styles.startButton} disabled={!canStart || isBusy || !isConnected} onClick={onStart} variant="unstyled">Start match →</Button>
          </div>
          <StatusMessage as="p" className={styles.startHint} icon="" status="info">{startHint}</StatusMessage>
          {message && <StatusMessage as="p" className={styles.startHint} status={messageStatus}>{message}</StatusMessage>}
        </div>
      </section>
      <section className={styles.channelSection} aria-label="Crew channel">
        <div className={styles.satelliteDock}><Satellite /><span className={styles.signalLine} aria-hidden="true" /></div>
        {isLive ? <ChatPanel className={styles.lobbyChat} messages={chatMessages} onSendMessage={onSendChat} isLive maxLength={500} title="Crew channel" emptyMessage="No signals yet. Say hello to your crew." messageStatus={connectionStatus === 'connected' ? 'Messages are shared with the room.' : 'Reconnect before sending a message.'} disabled={!canSendChat} disabledMessage={connectionStatus !== 'connected' ? 'Reconnect before sending a message.' : !currentPlayer?.isAlive ? 'Eliminated players cannot send messages.' : ''} />
          : <div className={styles.previewChannel}><p>CREW CHANNEL / PREVIEW</p><h2>Comms come online in a live room</h2><span>Invite your crew with the room code to start chatting.</span></div>}
      </section>
      <footer className={styles.footer}>BUGSY · {isLive ? 'LIVE ROOM' : 'LOCAL PREVIEW'}</footer>
    </div>
    {leaveOpen && <div className={styles.leaveBackdrop} onMouseDown={(event) => { if (event.target === event.currentTarget) setLeaveOpen(false); }}>
      <section aria-label="Leave this room?" aria-modal="true" className={styles.leaveDialog} ref={leaveCancelRef} role="dialog">
        <p>EXIT DOCKING BAY</p><h2>Leave this room?</h2>
        <span>Your seat will open for another player.</span>
        <div><Button className={styles.cancelLeave} onClick={() => setLeaveOpen(false)} variant="unstyled">Stay here</Button>
          <Button className={styles.confirmLeave} disabled={isBusy} onClick={() => { setLeaveOpen(false); onBack(); }} variant="unstyled">Leave room</Button></div>
      </section>
    </div>}
  </main>;
}
