/**
 * Local-only fixtures and deterministic preview rules for the Phase 2 UI.
 * These values are demonstration content, not authoritative game state.
 */

export const PREVIEW_MATCH = Object.freeze({
  minimumPlayers: 4,
  maxPlayers: 5,
  totalRounds: 4,
  roundSeconds: 60,
  discussionSeconds: 30,
});

export const ROOM_CODE_CHARACTERS = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
export const ROOM_CODE_LENGTH = 6;
export const SKIP_VOTE = 'skip';

export const PREVIEW_JOIN_CODES = Object.freeze({
  available: 'ABC234',
  full: 'FULL34',
  expired: 'EXPRD2',
  serverError: 'SRVERR',
});

export const CATEGORIES = [
  { id: 'data-structures', name: 'Data Structures & Algorithms', description: 'Patterns, collections, and efficient solutions.' },
  { id: 'object-oriented', name: 'Object-Oriented Programming', description: 'Classes, objects, and clean behavior.' },
  { id: 'security', name: 'Security', description: 'Trust boundaries, validation, and safe code.' },
  { id: 'frontend', name: 'Front-End', description: 'Interfaces, browser behavior, and user experience.' },
  { id: 'backend', name: 'Back-End', description: 'APIs, services, and data flow.' },
  { id: 'c-plus-plus', name: 'C++', description: 'Repair a small C++20 program together.' },
];

export const PREVIEW_PEER_VOTES = Object.freeze({
  'preview-maya': 'object-oriented',
  'preview-jules': 'data-structures',
  'preview-ari': 'object-oriented',
});

export const INITIAL_ARENA_CHAT = [
  { id: 'chat-1', name: 'Maya', tone: 'violet', text: 'I’ll inspect the failing method first.' },
  { id: 'chat-2', name: 'Jules', tone: 'mint', text: 'I see a TODO near the reset logic.' },
];

export const INITIAL_DISCUSSION = [];

export const CHALLENGES = {
  'data-structures': {
    title: 'Repair the task queue',
    summary: 'Fix the queue so items are added and removed in first-in, first-out order.',
    starterCode: `class TaskQueue:\n    def __init__(self):\n        self.items = []\n\n    def enqueue(self, item):\n        # TODO: add item to the back of the queue\n        pass\n\n    def dequeue(self):\n        # TODO: return and remove the oldest item\n        pass`,
    testNames: ['New items are added', 'Oldest item leaves first', 'Empty queue is handled'],
  },
  'object-oriented': {
    title: 'Repair the counter',
    summary: 'Correct the counter methods while preserving the object’s change history.',
    starterCode: `class Counter:\n    def __init__(self):\n        self.count = 0\n        self.history = []\n\n    def increment(self):\n        self.count += 1\n        self.history.append("inc")\n\n    def decrement(self):\n        # TODO: subtract one and record the change\n        self.count -= 2\n        self.history.append("dec")\n\n    def reset(self):\n        # TODO: reset the count to zero\n        pass`,
    testNames: ['Increment changes count', 'Decrement changes count by one', 'Reset returns to zero'],
  },
  security: {
    title: 'Repair the input validator',
    summary: 'Reject unsafe input consistently before it reaches the application.',
    starterCode: `def is_valid_username(value):\n    # TODO: reject empty values and values longer than 24 chars\n    if value is None:\n        return True\n\n    # TODO: allow only letters, digits, and underscores\n    return True`,
    testNames: ['Empty input is rejected', 'Length limit is enforced', 'Unsafe characters are rejected'],
  },
  frontend: {
    title: 'Repair the form state',
    summary: 'Keep the submit state accurate when a user edits and submits a form.',
    starterCode: `def submit_form(values):\n    # TODO: reject a form with a blank email\n    email = values.get("email", "")\n\n    if email:\n        return {"submitted": True, "email": email}\n\n    # TODO: report invalid form state\n    return {"submitted": True, "email": email}`,
    testNames: ['Valid email can submit', 'Blank email is rejected', 'Submitted email is preserved'],
  },
  backend: {
    title: 'Repair the response builder',
    summary: 'Return a predictable API response and handle missing records safely.',
    starterCode: `def build_user_response(user):\n    # TODO: return None when the user does not exist\n    if user is None:\n        return {}\n\n    return {\n        "id": user.get("id"),\n        # TODO: include the display name from the record\n        "name": user.get("username"),\n    }`,
    testNames: ['Missing user is handled', 'Response contains an ID', 'Display name uses the right field'],
  },
  'c-plus-plus': {
    title: 'Repair the score',
    summary: 'Fix score operations in C++20.',
    starterCode: 'extern "C" int add_score(int current, int points) { return current + points; }\n',
    testNames: ['Add points', 'Subtract points', 'Reset score'],
  },
};

export function countCategoryVotes(votes) {
  return Object.values(votes).reduce((counts, categoryId) => {
    counts[categoryId] = (counts[categoryId] ?? 0) + 1;
    return counts;
  }, {});
}

export function resolvePreviewCategoryVote(votes, roomCode) {
  const voteCounts = countCategoryVotes(votes);
  const highestCount = Math.max(0, ...Object.values(voteCounts));
  const tiedCategoryIds = CATEGORIES
    .filter((category) => (voteCounts[category.id] ?? 0) === highestCount && highestCount > 0)
    .map((category) => category.id);

  if (tiedCategoryIds.length === 0) {
    return { categoryId: null, voteCounts, wasTie: false };
  }

  // A stable room-code hash makes a preview tie repeatable for this room.
  const roomSeed = [...roomCode].reduce((sum, character) => sum + character.charCodeAt(0), 0);
  const winningCategoryId = tiedCategoryIds[roomSeed % tiedCategoryIds.length];

  return {
    categoryId: winningCategoryId,
    voteCounts,
    wasTie: tiedCategoryIds.length > 1,
  };
}

export function findPreviewImpostorId(room, matchSeed = 0) {
  if (!room?.players?.length) return null;

  const roomSeed = [...room.code].reduce(
    (sum, character) => sum + character.charCodeAt(0),
    0,
  );
  const impostorIndex = (roomSeed + matchSeed) % room.players.length;
  return room.players[impostorIndex].id;
}

export function buildPreviewPeerVotes(room) {
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

export function resolvePreviewPlayerVote(votes) {
  const voteCounts = Object.values(votes).reduce((counts, choice) => {
    counts[choice] = (counts[choice] ?? 0) + 1;
    return counts;
  }, {});
  const playerVoteCounts = Object.entries(voteCounts)
    .filter(([choice]) => choice !== SKIP_VOTE);

  if (playerVoteCounts.length === 0) {
    return { reason: 'all-skipped', voteCounts };
  }

  const highestCount = Math.max(...Object.values(voteCounts));
  const leaders = Object.entries(voteCounts)
    .filter(([, count]) => count === highestCount)
    .map(([choice]) => choice);

  if (leaders.length > 1) {
    return { reason: 'tie', voteCounts };
  }

  if (leaders[0] === SKIP_VOTE) {
    return { reason: 'skip-wins', voteCounts };
  }

  return { reason: 'ejected', ejectedPlayerId: leaders[0], voteCounts };
}

export function createRoomCode() {
  return Array.from({ length: ROOM_CODE_LENGTH }, () => {
    const index = Math.floor(Math.random() * ROOM_CODE_CHARACTERS.length);
    return ROOM_CODE_CHARACTERS[index];
  }).join('');
}

export function buildPreviewRoom(displayName, roomCode, isCreating, avatarId = 'linux-builder') {
  const localPlayer = {
    id: 'local-player',
    name: displayName,
    avatarId,
    isYou: true,
    isDemo: false,
    ready: false,
    isAlive: true,
    isConnected: true,
    tone: 'coral',
    isHost: isCreating,
  };
  const previewPlayers = [
    { id: 'preview-maya', name: 'Maya', tone: 'violet' },
    { id: 'preview-jules', name: 'Jules', tone: 'mint' },
    { id: 'preview-ari', name: 'Ari', tone: 'gold' },
  ].map((player, index) => ({
    ...player,
    avatarId: ['apple-inventor', 'apollo-coder', 'python-creator'][index],
    isYou: false,
    isDemo: true,
    isHost: !isCreating && index === 0,
    ready: true,
    isAlive: true,
    isConnected: true,
  }));

  return {
    code: roomCode,
    capacity: PREVIEW_MATCH.maxPlayers,
    currentPlayerId: localPlayer.id,
    players: isCreating
      ? [localPlayer, ...previewPlayers]
      : [...previewPlayers, localPlayer],
  };
}
