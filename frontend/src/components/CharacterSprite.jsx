import { getCharacter } from '../data/characters.js';
import styles from '../styles/components/CharacterSprite.module.css';

const POSITIONS = {
  idle: [0, 0], selected: [1, 0], ready: [2, 0], coding: [3, 0],
  meeting: [0, 1], win: [1, 1], loss: [2, 1],
};

export default function CharacterSprite({ id, state = 'idle', className = '', decorative = false, animate = true }) {
  const character = getCharacter(id);
  const [column, row] = POSITIONS[state] ?? POSITIONS.idle;
  return <span
    aria-hidden={decorative || undefined}
    aria-label={decorative ? undefined : `${character.name}, ${state}`}
    className={`${styles.sprite} ${styles[state] ?? ''} ${animate ? '' : styles.still} ${className}`.trim()}
    role={decorative ? undefined : 'img'}
    style={{
      backgroundImage: `url(${import.meta.env.BASE_URL}characters/${character.id}.webp)`,
      backgroundPosition: `${column * 100 / 3}% ${row * 100}%`,
    }}
  />;
}
