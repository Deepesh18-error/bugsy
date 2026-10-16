import { useState } from 'react';
import CategoryVoteScreen from './screens/CategoryVoteScreen.jsx';
import LobbyScreen from './screens/LobbyScreen.jsx';
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

  function handleLeaveLobby() {
    setRoom(null);
    setLobbyMessage('');
    setCategoryVotes({});
    setMyCategoryVote(null);
    setCategoryResult(null);
    setScreen('welcome');
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
