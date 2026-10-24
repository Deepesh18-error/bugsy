import { requireRoomSnapshot } from './rooms.js';

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
        || !isRecord(value.payload)) {
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
