import styles from '../styles/components/SabotageObjectives.module.css';

/** Receives only this player's authorized objective projection. */
export default function SabotageObjectives({ objectives = [] }) {
  if (!objectives.length) return null;

  return <section className={styles.panel} aria-labelledby="private-objectives-title">
    <p className={styles.eyebrow}>PRIVATE · IMPOSTOR ONLY</p>
    <h2 id="private-objectives-title">Sabotage objectives</h2>
    <p className={styles.note}>Progress comes from official server checks. A failing test alone does not identify who changed the code.</p>
    <ul className={styles.list}>
      {objectives.map((objective) => <li key={objective.objective_id} className={styles.item}>
        <span className={styles.status} data-status={objective.status}>
          {objective.status === 'completed' ? 'Verified'
            : objective.status === 'in_progress' ? 'In progress' : 'Pending'}
        </span>
        <p>{objective.private_description}</p>
      </li>)}
    </ul>
  </section>;
}
