import { roomWebSocketUrl } from './rooms.js';
import { parseServerMessage, ROOM_PROTOCOL_VERSION, RoomProtocolError } from './websocketProtocol.js';

export class RoomSocketError extends Error {
  constructor(code, message) {
    super(message);
    this.name = 'RoomSocketError';
    this.code = code;
  }
}

function newRequestId() {
  if (globalThis.crypto.randomUUID) return globalThis.crypto.randomUUID().replaceAll('-', '');
  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
}

/** One room connection. Pending commands retain their IDs across reconnects. */
export class RoomSocket {
  constructor({ onOpen, onClose, onMessage, onProtocolError }) {
    this.socket = null;
    this.pending = new Map();
    this.disposed = false;
    this.onOpen = onOpen;
    this.onClose = onClose;
    this.onMessage = onMessage;
    this.onProtocolError = onProtocolError;
  }

  connect() {
    if (this.disposed) return;
    if (this.socket && this.socket.readyState <= WebSocket.OPEN) return;

    const socket = new WebSocket(roomWebSocketUrl());
    this.socket = socket;
    socket.addEventListener('open', () => {
      if (this.socket !== socket || this.disposed) return;
      for (const { envelope } of this.pending.values()) {
        try {
          socket.send(JSON.stringify(envelope));
        } catch {
          socket.close();
          return;
        }
      }
      this.onOpen();
    });
    socket.addEventListener('message', (event) => {
      if (this.socket !== socket || this.disposed) return;
      let message;
      try {
        message = parseServerMessage(event.data);
      } catch (error) {
        this.onProtocolError(error instanceof RoomProtocolError
          ? error : new RoomProtocolError('The room message is invalid.'));
        socket.close(1002, 'Incompatible room protocol.');
        return;
      }
      if ((message.type === 'ack' || message.type === 'error') && message.request_id) {
        const pending = this.pending.get(message.request_id);
        if (pending) {
          this.pending.delete(message.request_id);
          if (message.type === 'ack') pending.resolve(message);
          else pending.reject(new RoomSocketError(message.code, message.message));
        }
      }
      this.onMessage(message);
    });
    socket.addEventListener('close', (event) => {
      if (this.socket !== socket || this.disposed) return;
      this.socket = null;
      this.onClose(event);
    });
  }

  isOpen() {
    return this.socket?.readyState === WebSocket.OPEN;
  }

  sendCommand(action) {
    if (!this.isOpen()) {
      return Promise.reject(new RoomSocketError('NOT_CONNECTED', 'Waiting to reconnect to the room.'));
    }
    const requestId = newRequestId();
    const envelope = {
      version: ROOM_PROTOCOL_VERSION,
      type: 'command',
      request_id: requestId,
      action,
    };
    return new Promise((resolve, reject) => {
      this.pending.set(requestId, { envelope, resolve, reject });
      try {
        this.socket.send(JSON.stringify(envelope));
      } catch {
        // Force a reconnect and resend this exact request ID.
        try {
          this.socket.close();
        } catch {
          this.pending.delete(requestId);
          reject(new RoomSocketError('SEND_FAILED', 'Could not send the room command.'));
        }
      }
    });
  }

  requestSnapshot() {
    if (!this.isOpen()) return false;
    try {
      this.socket.send(JSON.stringify({
        version: ROOM_PROTOCOL_VERSION,
        type: 'snapshot_request',
        request_id: newRequestId(),
      }));
      return true;
    } catch {
      this.socket.close();
      return false;
    }
  }

  sendPing() {
    if (!this.isOpen()) return;
    try {
      this.socket.send(JSON.stringify({
        version: ROOM_PROTOCOL_VERSION,
        type: 'ping',
        nonce: newRequestId(),
      }));
    } catch {
      this.socket.close();
    }
  }

  close() {
    this.disposed = true;
    for (const { reject } of this.pending.values()) {
      reject(new RoomSocketError('CONNECTION_CLOSED', 'The room connection was closed.'));
    }
    this.pending.clear();
    const socket = this.socket;
    this.socket = null;
    if (socket && socket.readyState < WebSocket.CLOSING) socket.close(1000, 'Leaving room.');
  }
}
