const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');

export const ROOM_CODE_LENGTH = 8;
export const ROOM_CODE_CHARACTERS = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';

export class RoomApiError extends Error {
  constructor(code, message) {
    super(message);
    this.name = 'RoomApiError';
    this.code = code;
  }
}

/**
 * Runtime check for the public RoomSnapshot in backend/app/api/schemas.py.
 * The browser deliberately accepts only the fields it needs for the lobby;
 * role and objective fields stay server-projected and are never inferred here.
 */
function requireRoomSnapshot(snapshot) {
  const validPhase = [
    'lobby', 'category_vote', 'role_reveal', 'coding_round',
    'meeting_discussion', 'player_vote', 'round_result', 'game_over',
  ];
  const isRecord = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
  if (!isRecord(snapshot)
    || typeof snapshot.room_code !== 'string'
    || !validPhase.includes(snapshot.phase)
    || !Number.isInteger(snapshot.capacity)
    || typeof snapshot.self_player_id !== 'string'
    || !Array.isArray(snapshot.players)
    || !snapshot.players.every((player) => isRecord(player)
      && typeof player.player_id === 'string'
      && typeof player.display_name === 'string'
      && ['connected', 'disconnected', 'departed'].includes(player.connection)
      && typeof player.is_ready === 'boolean'
      && typeof player.is_alive === 'boolean'
      && typeof player.is_host === 'boolean')) {
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
