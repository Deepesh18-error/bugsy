import { requireRoomSnapshot, SERVER_CATEGORY_IDS } from './rooms.js';

export const ROOM_PROTOCOL_VERSION = 1;

export class RoomProtocolError extends Error {
  constructor(message) {
    super(message);
    this.name = 'RoomProtocolError';
  }
}

const isRecord = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const isSequence = (value) => Number.isSafeInteger(value) && value >= 0;
const isRequestId = (value) => typeof value === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(value);
const hasExactKeys = (value, keys) => isRecord(value)
  && Object.keys(value).length === keys.length
  && keys.every((key) => Object.hasOwn(value, key));
const isPlayerId = (value) => typeof value === 'string' && value.length > 0 && value.length <= 128;
const isCounts = (value) => isRecord(value)
  && Object.entries(value).every(([categoryId, count]) => SERVER_CATEGORY_IDS.includes(categoryId)
    && Number.isSafeInteger(count) && count >= 0);

const eventPayloadChecks = {
  MatchStarted: (payload) => hasExactKeys(payload, []),
  PlayerReadinessChanged: (payload) => hasExactKeys(payload, ['player_id', 'is_ready'])
    && isPlayerId(payload.player_id) && typeof payload.is_ready === 'boolean',
  CategoryVoteRecorded: (payload) => hasExactKeys(payload, ['recorded'])
    && payload.recorded === true,
  CategorySelected: (payload) => hasExactKeys(payload, ['category_id', 'vote_counts', 'used_fallback'])
    && SERVER_CATEGORY_IDS.includes(payload.category_id)
    && isCounts(payload.vote_counts)
    && typeof payload.used_fallback === 'boolean',
  PlayerRoleAssigned: (payload) => hasExactKeys(payload, ['role'])
    && ['civilian', 'impostor'].includes(payload.role),
  CodingRoundStarted: (payload) => hasExactKeys(payload, [
    'round_number', 'category_id', 'challenge_id', 'challenge_version', 'deadline_at',
  ]) && Number.isInteger(payload.round_number) && payload.round_number >= 1
    && payload.round_number <= 4 && SERVER_CATEGORY_IDS.includes(payload.category_id)
    && typeof payload.challenge_id === 'string' && payload.challenge_id.length > 0
    && typeof payload.challenge_version === 'string' && payload.challenge_version.length > 0
    && typeof payload.deadline_at === 'string' && Number.isFinite(Date.parse(payload.deadline_at)),
  SourceRevisionChanged: (payload) => hasExactKeys(payload, ['source_revision_id'])
    && typeof payload.source_revision_id === 'string' && payload.source_revision_id.length > 0,
  SourceRevisionRestored: (payload) => hasExactKeys(payload, [
    'source_revision_id', 'restored_from_revision_id', 'restored_by_player_id',
  ]) && typeof payload.source_revision_id === 'string' && payload.source_revision_id.length > 0
    && typeof payload.restored_from_revision_id === 'string' && payload.restored_from_revision_id.length > 0
    && isPlayerId(payload.restored_by_player_id),
  OfficialTestRunRequested: (payload) => hasExactKeys(payload, ['source_revision_id'])
    && typeof payload.source_revision_id === 'string' && payload.source_revision_id.length > 0,
  MatchEnded: (payload) => hasExactKeys(payload, ['winner', 'reason', 'round_number'])
    && ['civilians', 'impostor'].includes(payload.winner)
    && typeof payload.reason === 'string' && Number.isInteger(payload.round_number),
  MeetingStarted: (payload) => hasExactKeys(payload, ['caller_player_id', 'discussion_deadline_at'])
    && isPlayerId(payload.caller_player_id) && typeof payload.discussion_deadline_at === 'string',
  PlayerVotingStarted: (payload) => hasExactKeys(payload, ['deadline_at'])
    && typeof payload.deadline_at === 'string',
  PlayerBallotStored: (payload) => hasExactKeys(payload, ['is_skip'])
    && typeof payload.is_skip === 'boolean',
  PlayerVoteResolved: (payload) => hasExactKeys(payload, [
    'vote_counts', 'skip_count', 'ejected_player_id', 'was_tie',
  ]) && isRecord(payload.vote_counts)
    && Object.values(payload.vote_counts).every((count) => Number.isInteger(count) && count >= 0)
    && Number.isInteger(payload.skip_count) && payload.skip_count >= 0
    && (payload.ejected_player_id === null || isPlayerId(payload.ejected_player_id))
    && typeof payload.was_tie === 'boolean',
  ChatMessagePosted: (payload) => hasExactKeys(payload, ['player_id', 'message'])
    && isPlayerId(payload.player_id) && typeof payload.message === 'string',
  SabotageObjectiveVerified: (payload) => hasExactKeys(payload, ['objective_id', 'source_revision_id'])
    && typeof payload.objective_id === 'string' && typeof payload.source_revision_id === 'string',
  OfficialTestRunStatusChanged: (payload) => hasExactKeys(payload, [
    'run_id', 'source_revision_id', 'status',
  ]) && typeof payload.run_id === 'string' && payload.run_id.length > 0
    && typeof payload.source_revision_id === 'string' && payload.source_revision_id.length > 0
    && ['queued', 'running', 'passed', 'failed', 'error', 'stale'].includes(payload.status),
  OfficialTestResult: (payload) => hasExactKeys(payload, [
    'run_id', 'source_revision_id', 'status', 'all_required_tests_passed', 'tests',
  ]) && typeof payload.run_id === 'string' && payload.run_id.length > 0
    && typeof payload.source_revision_id === 'string' && payload.source_revision_id.length > 0
    && payload.status === 'completed'
    && typeof payload.all_required_tests_passed === 'boolean'
    && Array.isArray(payload.tests) && payload.tests.length <= 32
    && payload.tests.every((test) => hasExactKeys(test, [
      'test_id', 'name', 'passed', 'required_for_civilian_win', 'message',
    ]) && typeof test.test_id === 'string' && test.test_id.length > 0
      && typeof test.name === 'string' && test.name.length > 0
      && typeof test.passed === 'boolean'
      && typeof test.required_for_civilian_win === 'boolean'
      && (test.message === null || typeof test.message === 'string')),
  RoundEnded: (payload) => hasExactKeys(payload, ['round_number', 'reason'])
    && Number.isInteger(payload.round_number) && payload.round_number >= 1 && payload.round_number <= 4
    && payload.reason === 'deadline_expired',
  PlayerDeparted: (payload) => hasExactKeys(payload, ['player_id'])
    && isPlayerId(payload.player_id),
  PlayerDisconnected: (payload) => hasExactKeys(payload, ['player_id'])
    && isPlayerId(payload.player_id),
  PlayerReconnected: (payload) => hasExactKeys(payload, ['player_id'])
    && isPlayerId(payload.player_id),
  HostTransferred: (payload) => hasExactKeys(payload, ['previous_host_player_id', 'new_host_player_id'])
    && isPlayerId(payload.previous_host_player_id)
    && isPlayerId(payload.new_host_player_id),
};

/** Decode only the server envelopes defined by websocket_schemas.py. */
export function parseServerMessage(raw) {
  let value;
  try {
    value = JSON.parse(raw);
  } catch {
    throw new RoomProtocolError('The room server sent unreadable data.');
  }
  if (!isRecord(value) || value.version !== ROOM_PROTOCOL_VERSION) {
    throw new RoomProtocolError('The room server uses an incompatible protocol version.');
  }

  switch (value.type) {
    case 'snapshot':
      if (!isSequence(value.sequence)
        || (value.request_id !== null && !isRequestId(value.request_id))) {
        throw new RoomProtocolError('The room snapshot has an invalid envelope.');
      }
      try {
        requireRoomSnapshot(value.room);
      } catch {
        throw new RoomProtocolError('The room snapshot is incompatible with this client.');
      }
      return value;
    case 'event':
      if (!isSequence(value.sequence) || value.sequence < 1
        || typeof value.name !== 'string' || !/^[A-Za-z0-9._-]{1,128}$/.test(value.name)
        || !isRecord(value.payload)
        || (Object.hasOwn(eventPayloadChecks, value.name)
          && !eventPayloadChecks[value.name](value.payload))) {
        throw new RoomProtocolError('The room event has an invalid envelope.');
      }
      return value;
    case 'ack':
      if (!isSequence(value.sequence) || !isRequestId(value.request_id)) {
        throw new RoomProtocolError('The command acknowledgment is invalid.');
      }
      return value;
    case 'error':
      if (typeof value.code !== 'string' || !/^[A-Za-z0-9._-]{1,128}$/.test(value.code)
        || typeof value.message !== 'string' || value.message.length < 1 || value.message.length > 160
        || (value.request_id !== null && !isRequestId(value.request_id))) {
        throw new RoomProtocolError('The room error has an invalid envelope.');
      }
      return value;
    case 'pong':
      if (typeof value.nonce !== 'string' || !/^[A-Za-z0-9._-]{1,128}$/.test(value.nonce)) {
        throw new RoomProtocolError('The room heartbeat response is invalid.');
      }
      return value;
    default:
      throw new RoomProtocolError('The room server sent an unknown message type.');
  }
}
