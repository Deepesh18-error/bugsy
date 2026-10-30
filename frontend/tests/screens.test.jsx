import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import WelcomeScreen from '../src/screens/WelcomeScreen.jsx';
import LobbyScreen from '../src/screens/LobbyScreen.jsx';
import VoteScreen from '../src/screens/VoteScreen.jsx';
import TestResults from '../src/components/TestResults.jsx';

const room = {
  code: 'TESTROOM', phase: 'lobby', capacity: 5, currentPlayerId: 'p1',
  players: [
    { id: 'p1', name: 'Ada', isYou: true, isHost: true, isConnected: true, isAlive: true, ready: true, tone: 'coral' },
    { id: 'p2', name: 'Bela', isConnected: true, isAlive: true, ready: true, tone: 'mint' },
    { id: 'p3', name: 'Cora', isConnected: true, isAlive: true, ready: true, tone: 'gold' },
    { id: 'p4', name: 'Davi', isConnected: true, isAlive: true, ready: true, tone: 'violet' },
  ],
};

describe('live screen actions', () => {
  it('validates a room code before calling the join handler', async () => {
    const join = vi.fn();
    render(<WelcomeScreen onCreateRoom={vi.fn()} onJoinRoom={join} onPreview={vi.fn()} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /Join room/ }));
    await user.type(screen.getByLabelText('Your player name'), 'Ada');
    await user.type(screen.getByLabelText('Room code'), 'ABC');
    await user.click(screen.getByRole('button', { name: 'Join' }));
    expect(join).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent('Room codes are 8 characters long.');
  });

  it('sends the selected character when creating a room', async () => {
    const create = vi.fn().mockResolvedValue(undefined);
    render(<WelcomeScreen onCreateRoom={create} onJoinRoom={vi.fn()} onPreview={vi.fn()} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /Create room/ }));
    await user.type(screen.getByLabelText('Your player name'), 'Ada');
    await user.click(screen.getByRole('radio', { name: 'Apollo Coder' }));
    await user.click(screen.getByRole('button', { name: /Create a room/ }));
    expect(create).toHaveBeenCalledWith('Ada', 'apollo-coder');
  });

  it('shows a concise inspiration credit on hover and keeps the chosen credit visible', async () => {
    render(<WelcomeScreen onCreateRoom={vi.fn()} onJoinRoom={vi.fn()} onPreview={vi.fn()} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /Create room/ }));
    await user.hover(screen.getByText('Apollo Coder'));
    expect(document.getElementById('character-credit')).toHaveTextContent('Margaret Hamilton · Led Apollo flight software');
    await user.unhover(screen.getByText('Apollo Coder'));
    expect(document.getElementById('character-credit')).toHaveTextContent('Linus Torvalds · Created Linux and Git');
  });

  it('permits a connected ready host to start, then disables start while disconnected', async () => {
    const onStart = vi.fn();
    const { rerender } = render(<LobbyScreen room={room} isLive connectionStatus="connected"
      onStart={onStart} onToggleReady={vi.fn()} onBack={vi.fn()} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /Start match/ }));
    expect(onStart).toHaveBeenCalledOnce();
    rerender(<LobbyScreen room={room} isLive connectionStatus="reconnecting"
      onStart={onStart} onToggleReady={vi.fn()} onBack={vi.fn()} />);
    expect(screen.getByRole('button', { name: /Start match/ })).toBeDisabled();
    expect(screen.getByText(/Reconnect to the room before changing readiness/)).toBeVisible();
  });

  it('locks a saved ballot without exposing counts before resolution', () => {
    render(<VoteScreen room={room} isLive hasVoted ownVoteTargetId="p2"
      selectedTargetId="p2" voteCounts={{ p2: 3 }} onSelectTarget={vi.fn()}
      onSubmitVote={vi.fn()} onContinue={vi.fn()} deadlineAt={new Date(Date.now() + 30_000).toISOString()} />);
    expect(screen.getByText('Your ballot for Bela is saved.')).toBeVisible();
    expect(screen.getByRole('button', { name: /Submit vote/ })).toBeDisabled();
    expect(screen.queryByText('FINAL TALLY')).not.toBeInTheDocument();
    expect(screen.queryByText('3 votes')).not.toBeInTheDocument();
  });

  it('labels an old official result stale and allows another run', () => {
    render(<TestResults bundle={{ tests: [] }} provisional={{ status: 'idle', outcomes: [] }}
      official={{ run_id: 'old-run', source_revision_id: 'old-revision', status: 'completed',
        all_required_tests_passed: true, tests: [] }} revisionId="new-revision"
      officialStatus="idle" canRun onRunProvisional={vi.fn()} onRunOfficial={vi.fn()} />);
    expect(screen.getByText('This official result belongs to an older revision.')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Run official tests' })).toBeEnabled();
    expect(screen.queryByRole('button', { name: 'Finalize verified solution' })).not.toBeInTheDocument();
  });

  it('offers only isolated official checks in a public build', () => {
    render(<TestResults bundle={{ tests: [] }} provisional={{ status: 'idle', outcomes: [] }}
      official={null} revisionId="saved-revision" officialStatus="idle" canRun
      browserFeedbackEnabled={false} onRunProvisional={vi.fn()} onRunOfficial={vi.fn()} />);
    expect(screen.queryByRole('button', { name: 'Run public checks' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Run official tests' })).toBeEnabled();
  });
});
