import styles from '../styles/components/PlayerCard.module.css';

export default function PlayerCard({
  player,
  variant = 'compact',
  className = '',
}) {
  const isEliminated = player.isAlive === false;
  const isDisconnected = player.isConnected === false || player.connected === false;
  const connectionLabel = isEliminated
    ? 'Ejected'
    : isDisconnected
      ? 'Disconnected'
      : 'Connected';
  const toneClass = styles[player.tone] ?? styles.neutral;

  return (
    <li className={`${styles.card} ${styles[variant] ?? ''} ${className}`.trim()}>
      <span className={`${styles.avatar} ${toneClass}`} aria-hidden="true">
        {player.name?.trim().slice(0, 1).toUpperCase() || '?'}
      </span>
      <span className={styles.identity}>
        <span className={styles.name}>
          {player.name || 'Unnamed player'}
          {player.isYou && <span className={styles.youBadge}>YOU</span>}
        </span>
        {variant === 'lobby' && (
          <span className={styles.meta}>
            {player.isHost ? `Room host · ${connectionLabel}` : connectionLabel}
            {player.isDemo && ' · sample player'}
          </span>
        )}
      </span>
      {player.isHost && <span className={styles.hostBadge}>HOST</span>}
      {variant === 'lobby' && player.ready !== undefined && (
        <span className={`${styles.readyBadge} ${player.ready ? styles.ready : styles.notReady}`}>
          <span aria-hidden="true">{player.ready ? '✓' : '·'}</span>
          {player.ready ? 'Ready' : 'Not ready'}
        </span>
      )}
      {variant !== 'lobby' && (
        <span className={`${styles.connection} ${isEliminated ? styles.eliminated : isDisconnected ? styles.disconnected : ''}`}>
          {player.isYou && !isEliminated ? 'YOU' : isEliminated ? 'EJECTED' : isDisconnected ? 'OFFLINE' : 'HERE'}
        </span>
      )}
    </li>
  );
}
