import { useState } from 'react';
import CategoryVoteScreen from './screens/CategoryVoteScreen.jsx';
import ArenaScreen from './screens/ArenaScreen.jsx';
import LobbyScreen from './screens/LobbyScreen.jsx';
import MeetingScreen from './screens/MeetingScreen.jsx';
import RoleRevealScreen from './screens/RoleRevealScreen.jsx';
import WelcomeScreen from './screens/WelcomeScreen.jsx';

const ROOM_CODE_CHARACTERS = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
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

function findPreviewImpostorId(room) {
  const roomSeed = [...room.code].reduce(
    (sum, character) => sum + character.charCodeAt(0),
    0,
  );
  const impostorIndex = roomSeed % room.players.length;
  return room.players[impostorIndex].id;
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

    const impostorId = findPreviewImpostorId(room);
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

  function handleResumeCoding() {
    setScreen('arena');
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

  if ((screen === 'arena' || screen === 'meeting') && room && privateRole && categoryResult) {
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
            roundNumber={1}
            totalRounds={4}
            isPaused={screen === 'meeting'}
            meetingAvailable={!hasUsedMeeting}
            onCallMeeting={handleCallMeeting}
          />
        </div>
        {screen === 'meeting' && (
          <MeetingScreen
            room={room}
            categoryName={selectedCategory?.name ?? 'Selected category'}
            roundNumber={1}
            onResumeCoding={handleResumeCoding}
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
