import { useEffect, useRef, useState } from 'react';
import { createRoom, joinRoom, leaveRoom, resumeRoom, toLobbyView } from './api/rooms.js';
import useRoomSocket from './hooks/useRoomSocket.js';
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
import StatusMessage from './components/StatusMessage.jsx';
import VoteScreen from './screens/VoteScreen.jsx';
import WelcomeScreen from './screens/WelcomeScreen.jsx';

// StrictMode replays mount effects in development. Reuse the same rotating
// credential request so two simultaneous resumes cannot invalidate each other.
let initialResumePromise;
function resumeAtStartup() {
  initialResumePromise ??= resumeRoom();
  return initialResumePromise;
}

const LIVE_CATEGORY_IDS = {
  'data-structures': 'data-structures-algorithms',
  frontend: 'front-end',
  backend: 'back-end',
};
const LIVE_CATEGORIES = CATEGORIES.map((category) => ({
  ...category,
  id: LIVE_CATEGORY_IDS[category.id] ?? category.id,
})).filter((category) => category.id === 'object-oriented');

export default function App() {
  const [screen, setScreen] = useState('welcome');
  const [room, setRoom] = useState(null);
  const [roomMode, setRoomMode] = useState(null);
  const [initialLiveSnapshot, setInitialLiveSnapshot] = useState(null);
  const [isRestoring, setIsRestoring] = useState(true);
  const [restoreError, setRestoreError] = useState('');
  const [isLobbyBusy, setIsLobbyBusy] = useState(false);
  const [isCategorySubmitting, setIsCategorySubmitting] = useState(false);
  const [categoryVoteMessage, setCategoryVoteMessage] = useState('');
  const [categoryVoteMessageStatus, setCategoryVoteMessageStatus] = useState('info');
  const [liveCategoryResult, setLiveCategoryResult] = useState(null);
  const [lobbyMessage, setLobbyMessage] = useState('');
  const [lobbyMessageStatus, setLobbyMessageStatus] = useState('info');
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
  const liveRoomCode = roomMode === 'live' ? room?.code : null;
  const liveSocket = useRoomSocket(liveRoomCode);
  const previousLivePlayers = useRef(null);
  const liveRoomSnapshot = roomMode === 'live'
    ? (liveSocket.snapshot?.room_code === liveRoomCode
      ? liveSocket.snapshot
      : initialLiveSnapshot?.room_code === liveRoomCode
        ? initialLiveSnapshot
        : null)
    : null;

  useEffect(() => {
    if (roomMode === 'live' && liveSocket.snapshot?.room_code === liveRoomCode) {
      const nextRoom = toLobbyView(liveSocket.snapshot);
      const previous = previousLivePlayers.current;
      if (previous?.code === nextRoom.code && nextRoom.phase === 'lobby') {
        const currentIds = new Set(nextRoom.players.map((player) => player.id));
        const departed = previous.players.filter((player) => !currentIds.has(player.id));
        const previousHostId = previous.players.find((player) => player.isHost)?.id;
        const nextHost = nextRoom.players.find((player) => player.isHost);
        if (departed.length) {
          const hostChanged = previousHostId && nextHost && previousHostId !== nextHost.id;
          setLobbyMessage(
            `${departed.map((player) => player.name).join(', ')} left the room.`
            + (hostChanged ? ` ${nextHost.name} is now the host.` : ''),
          );
          setLobbyMessageStatus('info');
        } else if (previousHostId && nextHost && previousHostId !== nextHost.id) {
          setLobbyMessage(`${nextHost.name} is now the host.`);
          setLobbyMessageStatus('info');
        }
      }
      previousLivePlayers.current = nextRoom;
      setRoom(nextRoom);
    }
  }, [roomMode, liveRoomCode, liveSocket.snapshot]);

  useEffect(() => {
    if (roomMode !== 'live' || liveSocket.status !== 'connected'
      || liveRoomSnapshot?.phase !== 'lobby') return undefined;
    // HTTP joins and departures do not yet publish a room event. Refreshing
    // the authorized snapshot keeps the lobby lineup accurate in this phase.
    const interval = window.setInterval(() => liveSocket.requestSnapshot(), 5_000);
    return () => window.clearInterval(interval);
  }, [roomMode, liveRoomSnapshot?.phase, liveSocket.status, liveSocket.requestSnapshot]);

  useEffect(() => {
    if (roomMode !== 'live' || liveSocket.lastEvent?.name !== 'CategorySelected') return;
    const payload = liveSocket.lastEvent.payload;
    setLiveCategoryResult({
      roomCode: liveRoomCode,
      categoryId: payload.category_id,
      voteCounts: payload.vote_counts,
      usedFallback: payload.used_fallback,
    });
  }, [roomMode, liveRoomCode, liveSocket.lastEvent]);

  useEffect(() => {
    if (roomMode === 'live' && liveRoomSnapshot?.own_category_vote_id) {
      setCategoryVoteMessage('Your vote is saved on the server. Waiting for the final result.');
      setCategoryVoteMessageStatus('success');
    }
  }, [roomMode, liveRoomSnapshot?.own_category_vote_id]);

  useEffect(() => {
    let active = true;
    resumeAtStartup().then((snapshot) => {
      if (!active) return;
      setRoom(toLobbyView(snapshot));
      setInitialLiveSnapshot(snapshot);
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
      setInitialLiveSnapshot(snapshot);
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
    setLiveCategoryResult(null);
    previousLivePlayers.current = null;
    setLobbyMessage('');
    setLobbyMessageStatus('info');
    setScreen('lobby');
  }

  async function handleCreateRoom(displayName) {
    const snapshot = await createRoom(displayName);
    setLiveCategoryResult(null);
    previousLivePlayers.current = null;
    setRoom(toLobbyView(snapshot));
    setInitialLiveSnapshot(snapshot);
    setRoomMode('live');
    setRestoreError('');
    setLobbyMessage('Room created. Share the code with friends.');
    setLobbyMessageStatus('success');
    setScreen('lobby');
  }

  async function handleJoinRoom(displayName, roomCode) {
    const snapshot = await joinRoom(displayName, roomCode);
    setLiveCategoryResult(null);
    previousLivePlayers.current = null;
    setRoom(toLobbyView(snapshot));
    setInitialLiveSnapshot(snapshot);
    setRoomMode('live');
    setRestoreError('');
    setLobbyMessage('You joined the room.');
    setLobbyMessageStatus('success');
    setScreen('lobby');
  }

  function handlePreview(displayName) {
    enterLobby(displayName, createRoomCode(), true);
  }

  async function handleLiveToggleReady() {
    const localPlayer = room?.players.find((player) => player.id === room.currentPlayerId);
    if (!localPlayer || room.phase !== 'lobby' || liveSocket.status !== 'connected') return;
    setIsLobbyBusy(true);
    setLobbyMessage('Saving your ready status…');
    setLobbyMessageStatus('loading');
    try {
      await liveSocket.sendCommand({ name: 'set_ready', ready: !localPlayer.ready });
      liveSocket.requestSnapshot();
      setLobbyMessage('Your ready status was saved.');
      setLobbyMessageStatus('success');
    } catch (error) {
      setLobbyMessage(error.message || 'Could not update your ready status.');
      setLobbyMessageStatus('error');
    } finally {
      setIsLobbyBusy(false);
    }
  }

  async function handleLiveStartMatch() {
    if (room?.phase !== 'lobby' || liveSocket.status !== 'connected') return;
    setIsLobbyBusy(true);
    setLobbyMessage('Asking the server to start the match…');
    setLobbyMessageStatus('loading');
    try {
      await liveSocket.sendCommand({ name: 'start_match' });
      setLiveCategoryResult(null);
      setCategoryVoteMessage('');
      setCategoryVoteMessageStatus('info');
      liveSocket.requestSnapshot();
      setLobbyMessage('The match is starting.');
      setLobbyMessageStatus('success');
    } catch (error) {
      setLobbyMessage(error.message || 'Could not start the match.');
      setLobbyMessageStatus('error');
    } finally {
      setIsLobbyBusy(false);
    }
  }

  async function handleLiveCategoryVote(categoryId) {
    if (liveRoomSnapshot?.phase !== 'category_vote'
      || liveRoomSnapshot.own_category_vote_id
      || isCategorySubmitting
      || liveSocket.status !== 'connected') return;
    if (!LIVE_CATEGORIES.some((category) => category.id === categoryId)) return;
    setIsCategorySubmitting(true);
    setCategoryVoteMessage('Sending your vote to the server…');
    setCategoryVoteMessageStatus('loading');
    try {
      await liveSocket.sendCommand({ name: 'cast_category_vote', category_id: categoryId });
      liveSocket.requestSnapshot();
      setCategoryVoteMessage('Vote recorded. Waiting for the group or deadline.');
      setCategoryVoteMessageStatus('success');
    } catch (error) {
      setCategoryVoteMessage(error.message || 'Could not record your vote.');
      setCategoryVoteMessageStatus('error');
    } finally {
      setIsCategorySubmitting(false);
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
    setInitialLiveSnapshot(null);
    setLiveCategoryResult(null);
    previousLivePlayers.current = null;
    setLobbyMessage('');
    setLobbyMessageStatus('info');
    setCategoryVotes({});
    setMyCategoryVote(null);
    setCategoryResult(null);
    setCategoryVoteMessage('');
    setCategoryVoteMessageStatus('info');
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
          setLobbyMessageStatus('error');
          setIsLobbyBusy(false);
          return;
        }
      }
      setIsLobbyBusy(false);
    }
    resetToWelcome();
  }

  if (roomMode === 'live' && room) {
    const phase = liveRoomSnapshot?.phase ?? room.phase;
    const liveResult = liveCategoryResult?.roomCode === room.code ? liveCategoryResult : null;
    const liveSelectedCategory = LIVE_CATEGORIES.find(
      (category) => category.id === liveRoomSnapshot?.selected_category_id,
    );

    if (phase === 'category_vote' || (phase === 'role_reveal' && liveResult)) {
      return (
        <CategoryVoteScreen
          categories={LIVE_CATEGORIES}
          roomCode={room.code}
          voteCounts={liveResult?.voteCounts ?? {}}
          selectedCategoryId={liveRoomSnapshot?.own_category_vote_id ?? null}
          result={liveResult}
          onVote={handleLiveCategoryVote}
          onContinue={() => setLiveCategoryResult(null)}
          canContinue={phase === 'role_reveal' && Boolean(liveRoomSnapshot?.own_role)}
          isLive
          isSubmitting={isCategorySubmitting}
          isDisabled={liveSocket.status !== 'connected'}
          statusMessage={liveSocket.error || (liveSocket.status !== 'connected'
            ? 'Connecting to the room before you can vote…'
            : categoryVoteMessage)}
          status={liveSocket.error ? 'error' : categoryVoteMessageStatus}
          deadlineAt={liveRoomSnapshot?.phase_deadline_at}
        />
      );
    }

    if (phase === 'role_reveal') {
      const currentPlayer = room.players.find((player) => player.id === room.currentPlayerId);
      return (
        <RoleRevealScreen
          displayName={currentPlayer?.name ?? 'Player'}
          role={liveRoomSnapshot?.own_role ?? null}
          category={liveSelectedCategory?.name ?? 'Selected category'}
          roomCode={room.code}
          isLive
          deadlineAt={liveRoomSnapshot?.phase_deadline_at}
        />
      );
    }

    if (phase === 'coding_round' && liveRoomSnapshot?.round_number) {
      return <ArenaScreen
        key={`${room.code}:${liveRoomSnapshot.round_number}`}
        isLive
        room={room}
        role={liveRoomSnapshot.own_role}
        categoryName={liveSelectedCategory?.name ?? 'Coding challenge'}
        roundNumber={liveRoomSnapshot.round_number}
        totalRounds={4}
        deadlineAt={liveRoomSnapshot.phase_deadline_at}
        revisionId={liveRoomSnapshot.current_source_revision_id}
        connectionStatus={liveSocket.status}
        officialEvent={liveSocket.lastOfficialResult}
        sendCommand={liveSocket.sendCommand}
      />;
    }

    if (phase !== 'lobby') {
      return (
        <main style={{ maxWidth: 720, margin: '4rem auto', padding: '1.5rem' }}>
          <h1>Live match</h1>
          <StatusMessage status="info">
            The server is in the {phase.replaceAll('_', ' ')} phase. This screen will be connected in a later phase.
          </StatusMessage>
        </main>
      );
    }

    return (
      <LobbyScreen
        room={room}
        message={lobbyMessage}
        messageStatus={lobbyMessageStatus}
        isLive
        isBusy={isLobbyBusy}
        connectionStatus={liveSocket.status}
        connectionError={liveSocket.error}
        hasSequenceGap={liveSocket.hasSequenceGap}
        lastEvent={liveSocket.lastEvent}
        onBack={handleLeaveLobby}
        onStart={handleLiveStartMatch}
        onToggleReady={handleLiveToggleReady}
      />
    );
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
        messageStatus={lobbyMessageStatus}
        isLive={false}
        isBusy={isLobbyBusy}
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
      onPreview={handlePreview}
      restoreError={restoreError}
      onRetryResume={handleRetryResume}
      isRestoring={isRestoring}
    />
  );
}
