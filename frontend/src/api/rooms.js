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
    'self_player_id', 'own_category_vote_id', 'has_cast_player_vote', 'own_player_vote_target_id',
    'own_meetings_used', 'meeting_cooldown_until', 'chat_messages', 'own_role', 'own_objectives',
    'selected_category_id', 'round_number', 'round_ended_at', 'round_end_reason',
    'challenge_id', 'challenge_version', 'current_source_revision_id',
    'official_result', 'official_runs', 'match_result', 'last_vote_result', 'players',
  ];
  const playerKeys = ['player_id', 'display_name', 'connection', 'is_ready', 'is_alive', 'is_host'];
  const objectiveKeys = ['objective_id', 'status', 'private_description'];
  const matchResultKeys = ['winner', 'reason', 'round_number'];
  const voteResultKeys = ['vote_counts', 'skip_count', 'ejected_player_id', 'was_tie', 'resolved_at'];
  const officialKeys = ['run_id', 'source_revision_id', 'status', 'all_required_tests_passed', 'tests'];
  const runKeys = ['run_id', 'source_revision_id', 'status', 'requested_at'];
  const resultTestKeys = ['test_id', 'name', 'passed', 'required_for_civilian_win', 'message'];
  const chatMessageKeys = ['message_id', 'player_id', 'display_name', 'message', 'sent_at'];
  if (!isRecord(snapshot)
    || !hasOnlyKeys(snapshot, snapshotKeys)
    || typeof snapshot.room_code !== 'string' || !snapshot.room_code
    || !validPhase.has(snapshot.phase)
    || ![4, 5].includes(snapshot.capacity)
    || !isUtcTime(snapshot.expires_at)
    || (snapshot.phase_deadline_at !== null && !isUtcTime(snapshot.phase_deadline_at))
    || typeof snapshot.self_player_id !== 'string' || !snapshot.self_player_id
    || !isCategory(snapshot.own_category_vote_id)
    || typeof snapshot.has_cast_player_vote !== 'boolean'
    || (snapshot.own_player_vote_target_id !== null
      && (typeof snapshot.own_player_vote_target_id !== 'string' || !snapshot.own_player_vote_target_id))
    || (!snapshot.has_cast_player_vote && snapshot.own_player_vote_target_id !== null)
    || !Number.isInteger(snapshot.own_meetings_used)
    || snapshot.own_meetings_used < 0
    || (snapshot.meeting_cooldown_until !== null && !isUtcTime(snapshot.meeting_cooldown_until))
    || !Array.isArray(snapshot.chat_messages) || snapshot.chat_messages.length > 100
    || !snapshot.chat_messages.every((message) => isRecord(message)
      && hasOnlyKeys(message, chatMessageKeys)
      && typeof message.message_id === 'string' && /^[0-9a-f]{64}$/.test(message.message_id)
      && typeof message.player_id === 'string' && message.player_id.length > 0
      && typeof message.display_name === 'string' && message.display_name.length > 0
      && message.display_name.length <= 96
      && typeof message.message === 'string' && message.message.length > 0
      && message.message.length <= 500 && message.message === message.message.trim()
      && isUtcTime(message.sent_at))
    || (snapshot.own_role !== null && !['civilian', 'impostor'].includes(snapshot.own_role))
    || !isCategory(snapshot.selected_category_id)
    || (snapshot.round_number !== null && (!Number.isInteger(snapshot.round_number)
      || snapshot.round_number < 0 || snapshot.round_number > 4))
    || (snapshot.round_ended_at !== null && !isUtcTime(snapshot.round_ended_at))
    || (snapshot.round_end_reason !== null
      && snapshot.round_end_reason !== 'deadline_expired')
    || (snapshot.challenge_id !== null && typeof snapshot.challenge_id !== 'string')
    || (snapshot.challenge_version !== null && typeof snapshot.challenge_version !== 'string')
    || (snapshot.current_source_revision_id !== null
      && typeof snapshot.current_source_revision_id !== 'string')
    || (snapshot.official_result != null && (!isRecord(snapshot.official_result)
      || !hasOnlyKeys(snapshot.official_result, officialKeys)
      || typeof snapshot.official_result.run_id !== 'string'
      || typeof snapshot.official_result.source_revision_id !== 'string'
      || snapshot.official_result.status !== 'completed'
      || typeof snapshot.official_result.all_required_tests_passed !== 'boolean'
      || !Array.isArray(snapshot.official_result.tests)
      || snapshot.official_result.tests.some((test) => !isRecord(test)
        || !hasOnlyKeys(test, resultTestKeys)
        || typeof test.test_id !== 'string' || typeof test.name !== 'string'
        || typeof test.passed !== 'boolean'
        || typeof test.required_for_civilian_win !== 'boolean'
        || (test.message !== null && typeof test.message !== 'string'))))
    || !Array.isArray(snapshot.own_objectives)
    || !snapshot.own_objectives.every((objective) => isRecord(objective)
      && hasOnlyKeys(objective, objectiveKeys)
      && typeof objective.objective_id === 'string'
      && typeof objective.private_description === 'string'
      && ['not_started', 'in_progress', 'completed'].includes(objective.status))
    || (snapshot.match_result !== null && (!isRecord(snapshot.match_result)
      || !hasOnlyKeys(snapshot.match_result, matchResultKeys)
      || !['civilians', 'impostor'].includes(snapshot.match_result.winner)
      || typeof snapshot.match_result.reason !== 'string'
      || !Number.isInteger(snapshot.match_result.round_number)))
    || (snapshot.last_vote_result !== null && (!isRecord(snapshot.last_vote_result)
      || !hasOnlyKeys(snapshot.last_vote_result, voteResultKeys)
      || !isRecord(snapshot.last_vote_result.vote_counts)
      || !Object.values(snapshot.last_vote_result.vote_counts).every((count) => Number.isInteger(count) && count >= 0)
      || !Number.isInteger(snapshot.last_vote_result.skip_count)
      || snapshot.last_vote_result.skip_count < 0
      || (snapshot.last_vote_result.ejected_player_id !== null
        && typeof snapshot.last_vote_result.ejected_player_id !== 'string')
      || typeof snapshot.last_vote_result.was_tie !== 'boolean'
      || !isUtcTime(snapshot.last_vote_result.resolved_at)))
    || !Array.isArray(snapshot.official_runs)
    || snapshot.official_runs.length > 32
    || !snapshot.official_runs.every((run) => isRecord(run)
      && hasOnlyKeys(run, runKeys)
      && typeof run.run_id === 'string'
      && typeof run.source_revision_id === 'string'
      && ['queued', 'running', 'passed', 'failed', 'error', 'stale'].includes(run.status)
      && isUtcTime(run.requested_at))
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
