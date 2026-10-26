import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { requireRoomSnapshot } from '../src/api/rooms.js';
import SabotageObjectives from '../src/components/SabotageObjectives.jsx';
import snapshot from './fixtures/impostor-snapshot.json';

describe('private sabotage contract', () => {
  it('accepts the server budget projection and rejects leaked or malformed budgets', () => {
    expect(requireRoomSnapshot(snapshot)).toBe(snapshot);
    for (const patch of [
      { own_sabotage_credits_remaining: -1 },
      { own_sabotage_credits_remaining: 4 },
      { own_sabotage_credits_remaining: '3' },
      { own_sabotage_cooldown_until: 'invalid' },
      { own_role: 'civilian' },
    ]) expect(() => requireRoomSnapshot({ ...snapshot, ...patch })).toThrow();
    expect(() => requireRoomSnapshot({ ...snapshot, own_role: 'civilian',
      own_sabotage_credits_remaining: null, own_sabotage_cooldown_until: null })).not.toThrow();
  });

  it('explains pending victory, the spent budget and cooldown', () => {
    render(<SabotageObjectives credits={2} cooldownSeconds={38} objectives={[
      { objective_id: 'target', status: 'completed', private_description: 'Change the target method.' },
    ]} />);
    expect(screen.getByText('Verified · defend until deadline')).toBeVisible();
    expect(screen.getByText(/2 verification credits left/)).toHaveTextContent('38s until another credit');
    expect(screen.getByText(/Credit requires your uninterrupted edits/)).toBeVisible();
  });
});
