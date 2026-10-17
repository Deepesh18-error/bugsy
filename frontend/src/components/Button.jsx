import styles from '../styles/components/Button.module.css';

export default function Button({
  children,
  variant = 'primary',
  size = 'medium',
  type = 'button',
  className = '',
  disabled = false,
  loading = false,
  loadingText = 'Working…',
  ...buttonProps
}) {
  const variantClass = variant === 'unstyled'
    ? ''
    : `${styles.button} ${styles[variant] ?? styles.primary} ${styles[size] ?? styles.medium}`;

  return (
    <button
      {...buttonProps}
      aria-busy={loading || undefined}
      className={`${variantClass} ${className}`.trim()}
      disabled={disabled || loading}
      type={type}
    >
      {loading && <span className={styles.spinner} aria-hidden="true" />}
      {loading ? loadingText : children}
    </button>
  );
}
