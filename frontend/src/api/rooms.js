const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');

export function roomWebSocketUrl() {
  const url = new URL(`${API_BASE_URL}/api/rooms/ws`);
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    throw new Error('The room API URL must use HTTP or HTTPS.');
  }
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  return url.toString();
}

export const ROOM_CODE_LENGTH = 8;
export const ROOM_CODE_CHARACTERS = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
export const SERVER_CATEGORY_IDS = Object.freeze([
  'data-structures-algorithms', 'object-oriented', 'security', 'front-end', 'back-end',
]);

export class RoomApiError extends Error {
  constructor(code, message) {
    super(message);
    this.name = 'RoomApiError';
    this.code = code;
  }
}

/**
 * Runtime check for the authorized RoomSnapshot in backend/app/api/schemas.py.
 * Role and ballot fields describe this authenticated guest only. The browser
 * never infers them from the room code or other players' public data.
 */
export function requireRoomSnapshot(snapshot) {
  const validPhase = new Set([
    'lobby', 'category_vote', 'role_reveal', 'coding_round',
    'meeting_discussion', 'player_vote', 'round_result', 'game_over',
  ]);
  const isRecord = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
  const hasOnlyKeys = (value, keys) => Object.keys(value).every((key) => keys.includes(key));
  const isUtcTime = (value) => typeof value === 'string'
    && /(Z|\+00:00)$/.test(value) && Number.isFinite(Date.parse(value));
  const isCategory = (value) => value === null || SERVER_CATEGORY_IDS.includes(value);
  const snapshotKeys = [
    'room_code', 'phase', 'capacity', 'expires_at', 'phase_deadline_at',
    'self_player_id', 'own_category_vote_id', 'own_role', 'own_objectives',
    'selected_category_id', 'round_number', 'challenge_id', 'challenge_version', 'players',
  ];
  const playerKeys = ['player_id', 'display_name', 'connection', 'is_ready', 'is_alive', 'is_host'];
  const objectiveKeys = ['objective_id', 'status'];
  if (!isRecord(snapshot)
    || !hasOnlyKeys(snapshot, snapshotKeys)
    || typeof snapshot.room_code !== 'string' || !snapshot.room_code
    || !validPhase.has(snapshot.phase)
    || ![4, 5].includes(snapshot.capacity)
    || !isUtcTime(snapshot.expires_at)
    || (snapshot.phase_deadline_at !== null && !isUtcTime(snapshot.phase_deadline_at))
    || typeof snapshot.self_player_id !== 'string' || !snapshot.self_player_id
    || !isCategory(snapshot.own_category_vote_id)
    || (snapshot.own_role !== null && !['civilian', 'impostor'].includes(snapshot.own_role))
    || !isCategory(snapshot.selected_category_id)
    || (snapshot.round_number !== null && (!Number.isInteger(snapshot.round_number)
      || snapshot.round_number < 0 || snapshot.round_number > 4))
    || (snapshot.challenge_id !== null && typeof snapshot.challenge_id !== 'string')
    || (snapshot.challenge_version !== null && typeof snapshot.challenge_version !== 'string')
    || !Array.isArray(snapshot.own_objectives)
    || !snapshot.own_objectives.every((objective) => isRecord(objective)
      && hasOnlyKeys(objective, objectiveKeys)
      && typeof objective.objective_id === 'string'
      && ['not_started', 'in_progress', 'completed'].includes(objective.status))
    || !Array.isArray(snapshot.players)
    || !snapshot.players.every((player) => isRecord(player)
      && hasOnlyKeys(player, playerKeys)
      && typeof player.player_id === 'string'
      && typeof player.display_name === 'string'
      && ['connected', 'disconnected', 'departed'].includes(player.connection)
      && typeof player.is_ready === 'boolean'
      && typeof player.is_alive === 'boolean'
      && typeof player.is_host === 'boolean')
    || !snapshot.players.some((player) => player.player_id === snapshot.self_player_id)) {
    throw new RoomApiError('INVALID_RESPONSE', 'The room server returned an incompatible room snapshot.');
  }
  return snapshot;
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}/api/rooms${path}`, {
      method: 'POST',
      credentials: 'include',
      cache: 'no-store',
      headers: options.body ? { 'Content-Type': 'application/json' } : undefined,
      body: options.body ? JSON.stringify(options.body) : undefined,
    });
  } catch {
    throw new RoomApiError('NETWORK_ERROR', 'Cannot reach the room server. Check that FastAPI and Redis are running.');
  }

  if (response.status === 204) return null;

  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new RoomApiError('INVALID_RESPONSE', 'The room server returned an unreadable response.');
  }

  if (!response.ok) {
    const error = payload?.error;
    const validationMessage = payload?.detail?.[0]?.msg;
    throw new RoomApiError(
      error?.code || (response.status === 422 ? 'INVALID_INPUT' : 'REQUEST_FAILED'),
      error?.message || validationMessage || 'The room request could not be completed.',
    );
  }

  return requireRoomSnapshot(payload?.room);
}

export function createRoom(displayName) {
  return request('', { body: { display_name: displayName, capacity: 5 } });
}

export function joinRoom(displayName, roomCode) {
  return request('/join', { body: { display_name: displayName, room_code: roomCode } });
}

export function resumeRoom() {
  return request('/resume');
}

export function leaveRoom() {
  return request('/leave');
}

// App's existing screen components use camelCase; this is the only translation
// from the backend's player-safe RoomSnapshot contract into that view model.
export function toLobbyView(snapshot) {
  const playerTones = ['coral', 'violet', 'mint', 'gold', 'neutral'];
  return {
    code: snapshot.room_code,
    phase: snapshot.phase,
    capacity: snapshot.capacity,
    currentPlayerId: snapshot.self_player_id,
    players: snapshot.players.map((player, index) => ({
      id: player.player_id,
      name: player.display_name,
      isYou: player.player_id === snapshot.self_player_id,
      isHost: player.is_host,
      isConnected: player.connection === 'connected',
      isAlive: player.is_alive,
      ready: player.is_ready,
      tone: playerTones[index % playerTones.length],
    })),
  };
}
