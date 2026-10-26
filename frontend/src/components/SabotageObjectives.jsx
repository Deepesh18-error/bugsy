import styles from '../styles/components/SabotageObjectives.module.css';

/** Receives only this player's authorized objective projection. */
export default function SabotageObjectives({ objectives = [], credits = null, cooldownSeconds = 0 }) {
  if (!objectives.length) return null;

  return <section className={styles.panel} aria-labelledby="private-objectives-title">
    <p className={styles.eyebrow}>PRIVATE · IMPOSTOR ONLY</p>
    <h2 id="private-objectives-title">Sabotage objectives</h2>
    <p className={styles.note}>Credit requires your uninterrupted edits to a previously tested revision, confined to the target method. Crashes, restores and mixed-author changes earn no credit. Keep the verified revision in place until the round deadline to win.</p>
    <p className={styles.note}>{credits ?? 3} verification credits left this match · {cooldownSeconds > 0 ? `${cooldownSeconds}s until another credit` : 'Verification ready'}. Each credited revision costs one credit and starts a 45-second cooldown. Credit closes 30 seconds before the round ends.</p>
    <ul className={styles.list}>
      {objectives.map((objective) => <li key={objective.objective_id} className={styles.item}>
        <span className={styles.status} data-status={objective.status}>
          {objective.status === 'completed' ? 'Verified · defend until deadline'
            : objective.status === 'in_progress' ? 'In progress' : 'Pending'}
        </span>
        <p>{objective.private_description}</p>
      </li>)}
    </ul>
  </section>;
}
