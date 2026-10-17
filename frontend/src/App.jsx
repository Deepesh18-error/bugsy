import { useState } from 'react';
import CategoryVoteScreen from './screens/CategoryVoteScreen.jsx';
import ArenaScreen from './screens/ArenaScreen.jsx';
import LobbyScreen from './screens/LobbyScreen.jsx';
import MeetingScreen from './screens/MeetingScreen.jsx';
import ResultsScreen from './screens/ResultsScreen.jsx';
import RoleRevealScreen from './screens/RoleRevealScreen.jsx';
import VoteScreen from './screens/VoteScreen.jsx';
import WelcomeScreen from './screens/WelcomeScreen.jsx';

const ROOM_CODE_CHARACTERS = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
const SKIP_VOTE = 'skip';
const CATEGORIES = [
  { id: 'data-structures', name: 'Data Structures & Algorithms', description: 'Patterns, collections, and efficient solutions.' },
  { id: 'object-oriented', name: 'Object-Oriented Programming', description: 'Classes, objects, and clean behavior.' },
  { id: 'security', name: 'Security', description: 'Trust boundaries, validation, and safe code.' },
  { id: 'frontend', name: 'Front-End', description: 'Interfaces, browser behavior, and user experience.' },
  { id: 'backend', name: 'Back-End', description: 'APIs, services, and data flow.' },
];
const PREVIEW_PEER_VOTES = {
  'preview-maya': 'object-oriented',
  'preview-jules': 'data-structures',
  'preview-ari': 'object-oriented',
};

function countCategoryVotes(votes) {
  return Object.values(votes).reduce((counts, categoryId) => {
    counts[categoryId] = (counts[categoryId] ?? 0) + 1;
    return counts;
  }, {});
}

function resolvePreviewVote(votes, roomCode) {
  const voteCounts = countCategoryVotes(votes);
  const highestCount = Math.max(...Object.values(voteCounts));
  const tiedCategoryIds = CATEGORIES
    .filter((category) => (voteCounts[category.id] ?? 0) === highestCount)
    .map((category) => category.id);

  // A stable room-code hash makes a preview tie repeatable for this room.
  const roomSeed = [...roomCode].reduce((sum, character) => sum + character.charCodeAt(0), 0);
  const winningCategoryId = tiedCategoryIds[roomSeed % tiedCategoryIds.length];

  return {
    categoryId: winningCategoryId,
    voteCounts,
    wasTie: tiedCategoryIds.length > 1,
  };
}

function findPreviewImpostorId(room, matchSeed = 0) {
  const roomSeed = [...room.code].reduce(
    (sum, character) => sum + character.charCodeAt(0),
    0,
  );
  const impostorIndex = (roomSeed + matchSeed) % room.players.length;
  return room.players[impostorIndex].id;
}

function buildPreviewPeerVotes(room) {
  const roomSeed = [...room.code].reduce(
    (sum, character) => sum + character.charCodeAt(0),
    0,
  );
  const livingPlayers = room.players.filter((player) => player.isAlive !== false);
  const simulatedVoters = livingPlayers.filter(
    (player) => player.id !== room.currentPlayerId,
  );

  return simulatedVoters.reduce((votes, voter, index) => {
    if (roomSeed % 5 === 0) {
      votes[voter.id] = SKIP_VOTE;
      return votes;
    }

    const possibleTargets = livingPlayers.filter((player) => player.id !== voter.id);
    const targetIndex = (roomSeed + index) % possibleTargets.length;
    votes[voter.id] = possibleTargets[targetIndex]?.id ?? SKIP_VOTE;
    return votes;
  }, {});
}

function resolvePreviewPlayerVote(votes) {
  const voteCounts = Object.values(votes).reduce((counts, choice) => {
    counts[choice] = (counts[choice] ?? 0) + 1;
    return counts;
  }, {});
  const playerVoteCounts = Object.entries(voteCounts)
    .filter(([choice]) => choice !== SKIP_VOTE);

  if (playerVoteCounts.length === 0) {
    return { reason: 'all-skipped', voteCounts };
  }

  const allVoteCounts = Object.entries(voteCounts);
  const highestCount = Math.max(...allVoteCounts.map(([, count]) => count));
  const leaders = allVoteCounts
    .filter(([, count]) => count === highestCount)
    .map(([choice]) => choice);

  if (leaders.length > 1) {
    return { reason: 'tie', voteCounts };
  }

  if (leaders[0] === SKIP_VOTE) {
    return { reason: 'skip-wins', voteCounts };
  }

  return {
    reason: 'ejected',
    ejectedPlayerId: leaders[0],
    voteCounts,
  };
}

function createRoomCode() {
  return Array.from({ length: 6 }, () => {
    const index = Math.floor(Math.random() * ROOM_CODE_CHARACTERS.length);
    return ROOM_CODE_CHARACTERS[index];
  }).join('');
}

function makePreviewPlayers(displayName, isCreating) {
  const localPlayer = {
    id: 'local-player',
    name: displayName,
    isYou: true,
    isDemo: false,
    ready: false,
    isAlive: true,
    tone: 'coral',
  };

  const previewPlayers = [
    { id: 'preview-maya', name: 'Maya', tone: 'violet' },
    { id: 'preview-jules', name: 'Jules', tone: 'mint' },
    { id: 'preview-ari', name: 'Ari', tone: 'gold' },
  ].map((player, index) => ({
    ...player,
    isYou: false,
    isDemo: true,
    isHost: !isCreating && index === 0,
    ready: true,
  }));

  return isCreating
    ? [{ ...localPlayer, isHost: true }, ...previewPlayers]
    : [...previewPlayers, { ...localPlayer, isHost: false }];
}

function buildPreviewRoom(displayName, roomCode, isCreating) {
  return {
    code: roomCode,
    capacity: 5,
    currentPlayerId: 'local-player',
    players: makePreviewPlayers(displayName, isCreating),
  };
}

export default function App() {
  const [screen, setScreen] = useState('welcome');
  const [room, setRoom] = useState(null);
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

  function enterLobby(displayName, roomCode, isCreating) {
    setRoom(buildPreviewRoom(displayName, roomCode, isCreating));
    setLobbyMessage('');
    setScreen('lobby');
  }

  function handleCreateRoom(displayName) {
    enterLobby(displayName, createRoomCode(), true);
  }

  function handleJoinRoom(displayName, roomCode) {
    // Room lookup is intentionally mocked in this front-end prototype.
    enterLobby(displayName, roomCode, false);
  }

  function handleToggleReady() {
    setRoom((currentRoom) => ({
      ...currentRoom,
      players: currentRoom.players.map((player) =>
        player.id === currentRoom.currentPlayerId
          ? { ...player, ready: !player.ready }
          : player,
      ),
    }));
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
    setCategoryResult(resolvePreviewVote(nextVotes, room.code));
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

    const isFinalRound = roundNumber >= 4;
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

  function handleLeaveLobby() {
    setRoom(null);
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
            totalRounds={4}
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
            totalRounds={4}
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
        onBack={handleLeaveLobby}
        onStart={handleStartMatch}
        onToggleReady={handleToggleReady}
      />
    );
  }

  return (
    <WelcomeScreen
      onCreateRoom={handleCreateRoom}
      onJoinRoom={handleJoinRoom}
    />
  );
}
