import { useCallback, useEffect, useRef, useState } from 'react';
import { RoomSocket, RoomSocketError } from '../api/roomSocket.js';

const HEARTBEAT_MS = 25_000;
const MAX_RECONNECT_MS = 10_000;
const FATAL_CLOSE_CODES = new Set([1002, 1003, 1008, 1009]);

export default function useRoomSocket(roomCode) {
  const socketRef = useRef(null);
  const [status, setStatus] = useState('idle');
  const [snapshot, setSnapshot] = useState(null);
  const [lastEvent, setLastEvent] = useState(null);
  const [error, setError] = useState('');
  const [hasSequenceGap, setHasSequenceGap] = useState(false);

  useEffect(() => {
    if (!roomCode) {
      socketRef.current = null;
      return undefined;
    }

    let active = true;
    let reconnectTimer;
    let heartbeatTimer;
    let attempts = 0;
    let snapshotSequence = -1;
    let observedSequence = -1;
    let requestedThrough = -1;
    setStatus('connecting');
    setSnapshot(null);
    setLastEvent(null);
    setError('');
    setHasSequenceGap(false);

    function requestLatest(client, sequence) {
      if (sequence <= snapshotSequence || sequence <= requestedThrough) return;
      if (client.requestSnapshot()) requestedThrough = sequence;
    }

    function failProtocol(message) {
      if (!active) return;
      setError(message);
      setStatus('error');
      client.close();
    }

    const client = new RoomSocket({
      onOpen: () => {
        if (!active) return;
        attempts = 0;
        setStatus('connected');
        setError('');
        clearInterval(heartbeatTimer);
        heartbeatTimer = window.setInterval(() => client.sendPing(), HEARTBEAT_MS);
      },
      onClose: (event) => {
        if (!active) return;
        clearInterval(heartbeatTimer);
        if (FATAL_CLOSE_CODES.has(event.code)) {
          setStatus('error');
          setError(event.code === 1008
            ? 'Your room session is no longer valid. Join again with the room code.'
            : 'The room connection is incompatible with this client.');
          client.close();
          return;
        }
        setStatus('reconnecting');
        attempts += 1;
        reconnectTimer = window.setTimeout(connect, Math.min(MAX_RECONNECT_MS, 1000 * 2 ** (attempts - 1)));
      },
      onProtocolError: (protocolError) => failProtocol(protocolError.message),
      onMessage: (message) => {
        if (!active) return;
        if (message.type === 'snapshot') {
          if (message.room.room_code !== roomCode) {
            failProtocol('The room server returned a different room.');
            return;
          }
          if (message.sequence >= snapshotSequence && message.sequence >= observedSequence) {
            snapshotSequence = message.sequence;
            setSnapshot(message.room);
          }
          if (snapshotSequence >= observedSequence) {
            setHasSequenceGap(false);
          } else {
            // A newer event arrived while the snapshot was in flight.
            requestedThrough = snapshotSequence;
            requestLatest(client, observedSequence);
          }
        } else if (message.type === 'event' || message.type === 'ack') {
          observedSequence = Math.max(observedSequence, message.sequence);
          if (message.type === 'event') setLastEvent(message);
          if (message.sequence > snapshotSequence + 1) setHasSequenceGap(true);
          requestLatest(client, message.sequence);
        } else if (message.type === 'error' && !message.request_id) {
          setError(message.message);
        }
      },
    });
    socketRef.current = client;

    function connect() {
      if (!active) return;
      try {
        client.connect();
      } catch {
        setStatus('reconnecting');
        attempts += 1;
        reconnectTimer = window.setTimeout(connect, Math.min(MAX_RECONNECT_MS, 1000 * 2 ** (attempts - 1)));
      }
    }
    connect();

    return () => {
      active = false;
      clearTimeout(reconnectTimer);
      clearInterval(heartbeatTimer);
      if (socketRef.current === client) socketRef.current = null;
      client.close();
    };
  }, [roomCode]);

  const sendCommand = useCallback((action) => {
    const socket = socketRef.current;
    if (!socket) return Promise.reject(new RoomSocketError('NOT_CONNECTED', 'Waiting to connect to the room.'));
    return socket.sendCommand(action);
  }, []);

  const requestSnapshot = useCallback(() => socketRef.current?.requestSnapshot() ?? false, []);

  return { status, snapshot, lastEvent, error, hasSequenceGap, sendCommand, requestSnapshot };
}
