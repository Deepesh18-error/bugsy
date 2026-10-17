import styles from '../styles/components/Panel.module.css';

export default function Panel({
  as: Element = 'section',
  variant = 'framed',
  className = '',
  children,
  ...panelProps
}) {
  return (
    <Element
      {...panelProps}
      className={`${styles.panel} ${styles[variant] ?? styles.framed} ${className}`.trim()}
    >
      {children}
    </Element>
  );
}
