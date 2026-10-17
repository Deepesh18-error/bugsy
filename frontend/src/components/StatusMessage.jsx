import styles from '../styles/components/StatusMessage.module.css';

const STATUS_ICONS = {
  info: 'i',
  success: '✓',
  error: '!',
  warning: '!',
  loading: '…',
  reconnecting: '↻',
};

export default function StatusMessage({
  status = 'info',
  children,
  className = '',
  as: Element = 'p',
  icon,
  role,
  ...messageProps
}) {
  const isKnownStatus = Object.hasOwn(STATUS_ICONS, status);
  const statusClass = isKnownStatus ? styles[status] : styles.info;
  const resolvedRole = role ?? (status === 'error' ? 'alert' : 'status');
  const resolvedIcon = icon ?? STATUS_ICONS[status] ?? STATUS_ICONS.info;

  return (
    <Element
      {...messageProps}
      aria-live={resolvedRole === 'alert' ? 'assertive' : 'polite'}
      className={`${styles.message} ${statusClass} ${className}`.trim()}
      role={resolvedRole}
    >
      {resolvedIcon && <span className={styles.icon} aria-hidden="true">{resolvedIcon}</span>}
      <span>{children}</span>
    </Element>
  );
}
