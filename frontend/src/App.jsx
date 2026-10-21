import { useEffect, useState } from 'react';
import { createRoom, joinRoom, leaveRoom, resumeRoom, toLobbyView } from './api/rooms.js';
import {
  buildPreviewPeerVotes,
  buildPreviewRoom,
  CATEGORIES,
  countCategoryVotes,
  createRoomCode,
  findPreviewImpostorId,
  PREVIEW_MATCH,
  PREVIEW_PEER_VOTES,
  resolvePreviewCategoryVote,
  resolvePreviewPlayerVote,
  SKIP_VOTE,
} from './data/mockMatch.js';
import CategoryVoteScreen from './screens/CategoryVoteScreen.jsx';
import ArenaScreen from './screens/ArenaScreen.jsx';
import LobbyScreen from './screens/LobbyScreen.jsx';
import MeetingScreen from './screens/MeetingScreen.jsx';
import ResultsScreen from './screens/ResultsScreen.jsx';
import RoleRevealScreen from './screens/RoleRevealScreen.jsx';
import VoteScreen from './screens/VoteScreen.jsx';
import WelcomeScreen from './screens/WelcomeScreen.jsx';

// StrictMode replays mount effects in development. Reuse the same rotating
// credential request so two simultaneous resumes cannot invalidate each other.
let initialResumePromise;
function resumeAtStartup() {
  initialResumePromise ??= resumeRoom();
  return initialResumePromise;
}

export default function App() {
  const [screen, setScreen] = useState('welcome');
  const [room, setRoom] = useState(null);
  const [roomMode, setRoomMode] = useState(null);
  const [isRestoring, setIsRestoring] = useState(true);
  const [restoreError, setRestoreError] = useState('');
  const [isLobbyBusy, setIsLobbyBusy] = useState(false);
  const [lobbyMessage, setLobbyMessage] = useState('');
  const [categoryVotes, setCategoryVotes] = useState({});
  const [myCategoryVote, setMyCategoryVote] = useState(null);
  const [categoryResult, setCategoryResult] = useState(null);
  const [privateRole, setPrivateRole] = useState(null);
  const [roleRevealMessage, setRoleRevealMessage] = useState('');
  const [hasUsedMeeting, setHasUsedMeeting] = useState(false);
  const [voteSelection, setVoteSelection] = useState(null);
  const [voteResult, setVoteResult] = useState(null);
  const [roundNumber, setRoundNumber] = useState(1);
  const [gameResult, setGameResult] = useState(null);
  const [matchSeed, setMatchSeed] = useState(0);

  useEffect(() => {
    let active = true;
    resumeAtStartup().then((snapshot) => {
      if (!active) return;
      setRoom(toLobbyView(snapshot));
      setRoomMode('live');
      setScreen('lobby');
    }).catch((error) => {
      if (active && error.code !== 'SESSION_INVALID') setRestoreError(error.message);
    }).finally(() => {
      if (active) setIsRestoring(false);
    });
    return () => { active = false; };
  }, []);

  async function handleRetryResume() {
    setIsRestoring(true);
    setRestoreError('');
    try {
      const snapshot = await resumeRoom();
      setRoom(toLobbyView(snapshot));
      setRoomMode('live');
      setScreen('lobby');
    } catch (error) {
      if (error.code !== 'SESSION_INVALID') setRestoreError(error.message);
    } finally {
      setIsRestoring(false);
    }
  }

  function enterLobby(displayName, roomCode, isCreating) {
    setRoom(buildPreviewRoom(displayName, roomCode, isCreating));
    setRoomMode('preview');
    setLobbyMessage('');
    setScreen('lobby');
  }

  async function handleCreateRoom(displayName) {
    const snapshot = await createRoom(displayName);
    setRoom(toLobbyView(snapshot));
    setRoomMode('live');
    setRestoreError('');
    setLobbyMessage('Room created. Share the code with friends.');
    setScreen('lobby');
  }

  async function handleJoinRoom(displayName, roomCode) {
    const snapshot = await joinRoom(displayName, roomCode);
    setRoom(toLobbyView(snapshot));
    setRoomMode('live');
    setRestoreError('');
    setLobbyMessage('You joined the room.');
    setScreen('lobby');
  }

  function handlePreview(displayName) {
    enterLobby(displayName, createRoomCode(), true);
  }

  async function handleRefreshLobby() {
    setIsLobbyBusy(true);
    setLobbyMessage('');
    try {
      const snapshot = await resumeRoom();
      setRoom(toLobbyView(snapshot));
      setLobbyMessage('Room membership refreshed.');
    } catch (error) {
      if (error.code === 'SESSION_INVALID') {
        resetToWelcome();
        setRestoreError('Your room session expired. Join again with the room code.');
      } else {
        setLobbyMessage(error.message);
      }
    } finally {
      setIsLobbyBusy(false);
    }
  }

  function handleToggleReady() {
    const localPlayer = room.players.find((player) => player.id === room.currentPlayerId);
    const localWillBeReady = !localPlayer?.ready;
    const otherPlayersAreReady = room.players
      .filter((player) => player.id !== room.currentPlayerId)
      .every((player) => player.ready);

    setRoom((currentRoom) => ({
      ...currentRoom,
      players: currentRoom.players.map((player) =>
        player.id === currentRoom.currentPlayerId
          ? { ...player, ready: !player.ready }
          : player,
      ),
    }));

    if (!localPlayer?.isHost && localWillBeReady && otherPlayersAreReady) {
      setLobbyMessage('Everyone is ready. The sample host is starting the preview…');
      window.setTimeout(handleStartMatch, 350);
      return;
    }

    setLobbyMessage('Your ready status was updated in this local preview.');
  }

  function handleStartMatch() {
    setCategoryVotes(PREVIEW_PEER_VOTES);
    setMyCategoryVote(null);
    setCategoryResult(null);
    setPrivateRole(null);
    setRoleRevealMessage('');
    setHasUsedMeeting(false);
    setVoteSelection(null);
    setVoteResult(null);
    setRoundNumber(1);
    setGameResult(null);
    setMatchSeed(0);
    setScreen('categoryVote');
  }

  function handleCategoryVote(categoryId) {
    if (!room || myCategoryVote) return;
    if (!CATEGORIES.some((category) => category.id === categoryId)) return;

    const nextVotes = {
      ...categoryVotes,
      [room.currentPlayerId]: categoryId,
    };
    setCategoryVotes(nextVotes);
    setMyCategoryVote(categoryId);
    setCategoryResult(resolvePreviewCategoryVote(nextVotes, room.code));
  }

  function handleRevealRole() {
    if (!room || !categoryResult) return;

    const impostorId = findPreviewImpostorId(room, matchSeed);
    const role = room.currentPlayerId === impostorId ? 'impostor' : 'civilian';

    setPrivateRole(role);
    setRoleRevealMessage('');
    setScreen('roleReveal');
  }

  function handleContinueFromRoleReveal() {
    setRoleRevealMessage('');
    setScreen('arena');
  }

  function handleCallMeeting() {
    if (!room || hasUsedMeeting) return;

    setHasUsedMeeting(true);
    setScreen('meeting');
  }

  function handleProceedToVote() {
    setVoteSelection(null);
    setVoteResult(null);
    setScreen('vote');
  }

  function handleSelectVote(choice) {
    if (voteResult || !room) return;

    const livingPlayers = room.players.filter((player) => player.isAlive !== false);
    const isValidChoice = choice === SKIP_VOTE || livingPlayers.some(
      (player) => player.id === choice && player.id !== room.currentPlayerId,
    );

    if (isValidChoice) setVoteSelection(choice);
  }

  function handleSubmitVote() {
    if (!room || !voteSelection || voteResult) return;

    const allVotes = {
      ...buildPreviewPeerVotes(room),
      [room.currentPlayerId]: voteSelection,
    };
    const result = resolvePreviewPlayerVote(allVotes);

    if (result.reason === 'ejected') {
      result.isImpostorEjected = result.ejectedPlayerId === findPreviewImpostorId(room, matchSeed);
    }

    setVoteResult(result);
  }

  function handleContinueAfterVote() {
    if (!room || !voteResult) return;

    const localPlayerWasEjected = voteResult.ejectedPlayerId === room.currentPlayerId;
    const isMatchOver = voteResult.isImpostorEjected || localPlayerWasEjected;
    const ejectedPlayer = voteResult.ejectedPlayerId
      ? room.players.find((player) => player.id === voteResult.ejectedPlayerId)
      : null;

    if (ejectedPlayer && !isMatchOver) {
      setRoom((currentRoom) => ({
        ...currentRoom,
        players: currentRoom.players.map((player) =>
          player.id === voteResult.ejectedPlayerId
            ? { ...player, isAlive: false }
            : player,
        ),
      }));
    }

    const voteTally = Object.fromEntries(
      Object.entries(voteResult.voteCounts).map(([choice, count]) => {
        const player = room.players.find((candidate) => candidate.id === choice);
        return [choice === SKIP_VOTE ? 'Skip' : player?.name ?? 'Unknown player', count];
      }),
    );

    setGameResult({
      type: isMatchOver ? 'match' : 'round',
      action: isMatchOver ? 'finish' : 'resume',
      headline: voteResult.isImpostorEjected
        ? 'The civilians found the impostor.'
        : localPlayerWasEjected
          ? 'Your player was voted out.'
          : ejectedPlayer
            ? `${ejectedPlayer.name} was voted out.`
            : 'No one was voted out.',
      description: voteResult.isImpostorEjected
        ? 'The impostor was ejected, so the civilians win this match.'
        : localPlayerWasEjected
          ? 'Your local player was ejected. The remaining match is outside this single-player preview.'
          : 'The meeting has ended. The coding round can continue.',
      summaryTitle: voteResult.reason === 'tie'
        ? 'The ballot ended in a tie'
        : voteResult.reason === 'all-skipped' || voteResult.reason === 'skip-wins'
          ? 'The group chose not to eject'
          : 'The vote selected a player',
      summary: ejectedPlayer
        ? `${ejectedPlayer.name} received the highest unique vote total.`
        : 'No player received a unique highest vote total, so there was no ejection.',
      outcomeLabel: isMatchOver ? 'MATCH ENDED' : ejectedPlayer ? 'PLAYER EJECTED' : 'NO EJECTION',
      voteCounts: voteTally,
      continueLabel: isMatchOver ? 'Finish preview' : 'Return to coding',
    });
    setScreen('results');
  }

  function handleRoundTimeout() {
    if (screen !== 'arena') return;

    const isFinalRound = roundNumber >= PREVIEW_MATCH.totalRounds;
    setGameResult({
      type: isFinalRound ? 'match' : 'round',
      action: isFinalRound ? 'finish' : 'next-round',
      headline: isFinalRound
        ? privateRole === 'impostor' ? 'You survived the final round.' : 'The impostor survived.'
        : `Round ${roundNumber} is over.`,
      description: isFinalRound
        ? 'The final coding deadline expired before the civilians removed the impostor.'
        : 'The round timer expired. The match continues with a fresh round.',
      summaryTitle: isFinalRound ? 'Final deadline reached' : 'Round deadline reached',
      summary: isFinalRound
        ? 'The impostor objective wins when the impostor survives through the final round deadline.'
        : 'This preview advances to the next round. Roles and the category stay the same.',
      outcomeLabel: isFinalRound ? 'IMPOSTOR WIN' : 'ROUND ENDED',
      continueLabel: isFinalRound ? 'Finish preview' : 'Start next round',
    });
    setScreen('results');
  }

  function handleContinueFromResults() {
    if (!gameResult) return;

    if (gameResult.action === 'next-round') {
      setRoundNumber((currentRound) => currentRound + 1);
      setVoteSelection(null);
      setVoteResult(null);
      setGameResult(null);
      setScreen('arena');
      return;
    }

    if (gameResult.action === 'resume') {
      setVoteSelection(null);
      setVoteResult(null);
      setGameResult(null);
      setScreen('arena');
      return;
    }

    handleLeaveLobby();
  }

  function handleRematch() {
    if (!room || gameResult?.type !== 'match') return;

    setRoom((currentRoom) => ({
      ...currentRoom,
      players: currentRoom.players.map((player) => ({ ...player, isAlive: true })),
    }));
    setCategoryVotes(PREVIEW_PEER_VOTES);
    setMyCategoryVote(null);
    setCategoryResult(null);
    setPrivateRole(null);
    setRoleRevealMessage('');
    setHasUsedMeeting(false);
    setVoteSelection(null);
    setVoteResult(null);
    setRoundNumber(1);
    setGameResult(null);
    setMatchSeed((currentSeed) => currentSeed + 1);
    setScreen('categoryVote');
  }

  function resetToWelcome() {
    setRoom(null);
    setRoomMode(null);
    setLobbyMessage('');
    setCategoryVotes({});
    setMyCategoryVote(null);
    setCategoryResult(null);
    setPrivateRole(null);
    setRoleRevealMessage('');
    setHasUsedMeeting(false);
    setVoteSelection(null);
    setVoteResult(null);
    setRoundNumber(1);
    setGameResult(null);
    setMatchSeed(0);
    setScreen('welcome');
  }

  async function handleLeaveLobby() {
    if (roomMode === 'live') {
      setIsLobbyBusy(true);
      setLobbyMessage('');
      try {
        await leaveRoom();
      } catch (error) {
        if (error.code !== 'SESSION_INVALID') {
          setLobbyMessage(error.message);
          setIsLobbyBusy(false);
          return;
        }
      }
      setIsLobbyBusy(false);
    }
    resetToWelcome();
  }

  if (screen === 'roleReveal' && room && privateRole) {
    const currentPlayer = room.players.find(
      (player) => player.id === room.currentPlayerId,
    );
    const selectedCategory = CATEGORIES.find(
      (category) => category.id === categoryResult?.categoryId,
    );

    return (
      <RoleRevealScreen
        displayName={currentPlayer?.name ?? 'Player'}
        role={privateRole}
        category={selectedCategory?.name ?? 'Selected category'}
        roomCode={room.code}
        message={roleRevealMessage}
        onContinue={handleContinueFromRoleReveal}
      />
    );
  }

  if ((screen === 'arena' || screen === 'meeting' || screen === 'vote' || screen === 'results') && room && privateRole && categoryResult) {
    const selectedCategory = CATEGORIES.find(
      (category) => category.id === categoryResult.categoryId,
    );

    return (
      <>
        <div hidden={screen !== 'arena'}>
          <ArenaScreen
            room={room}
            role={privateRole}
            categoryId={categoryResult.categoryId}
            categoryName={selectedCategory?.name ?? 'Selected category'}
            key={roundNumber}
            roundNumber={roundNumber}
            totalRounds={PREVIEW_MATCH.totalRounds}
            isPaused={screen !== 'arena'}
            meetingAvailable={!hasUsedMeeting}
            onCallMeeting={handleCallMeeting}
            onRoundTimeout={handleRoundTimeout}
          />
        </div>
        {screen === 'meeting' && (
          <MeetingScreen
            room={room}
            categoryName={selectedCategory?.name ?? 'Selected category'}
            roundNumber={roundNumber}
            onProceedToVote={handleProceedToVote}
          />
        )}
        {screen === 'vote' && (
          <VoteScreen
            room={room}
            selectedTargetId={voteSelection}
            voteCounts={voteResult?.voteCounts ?? {}}
            voteResult={voteResult}
            isLocalPlayerEjected={voteResult?.ejectedPlayerId === room.currentPlayerId}
            onSelectTarget={handleSelectVote}
            onSubmitVote={handleSubmitVote}
            onContinue={handleContinueAfterVote}
          />
        )}
        {screen === 'results' && gameResult && (
          <ResultsScreen
            roomCode={room.code}
            roundNumber={roundNumber}
            totalRounds={PREVIEW_MATCH.totalRounds}
            result={gameResult}
            onContinue={handleContinueFromResults}
            onRematch={handleRematch}
          />
        )}
      </>
    );
  }

  if (screen === 'categoryVote' && room) {
    return (
      <CategoryVoteScreen
        categories={CATEGORIES}
        roomCode={room.code}
        voteCounts={countCategoryVotes(categoryVotes)}
        selectedCategoryId={myCategoryVote}
        result={categoryResult}
        onVote={handleCategoryVote}
        onContinue={handleRevealRole}
      />
    );
  }

  if (screen === 'lobby' && room) {
    return (
      <LobbyScreen
        room={room} 
        message={lobbyMessage}
        isLive={roomMode === 'live'}
        isBusy={isLobbyBusy}
        onBack={handleLeaveLobby}
        onRefresh={handleRefreshLobby}
        onStart={handleStartMatch}
        onToggleReady={handleToggleReady}
      />
    );
  }

  return (
    <WelcomeScreen
      onCreateRoom={handleCreateRoom}
      onJoinRoom={handleJoinRoom}
      onPreview={handlePreview}
      restoreError={restoreError}
      onRetryResume={handleRetryResume}
      isRestoring={isRestoring}
    />
  );
}
