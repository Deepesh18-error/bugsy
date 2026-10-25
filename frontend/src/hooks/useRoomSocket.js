import { useCallback, useEffect, useRef, useState } from 'react';
import { RoomSocket, RoomSocketError } from '../api/roomSocket.js';

const HEARTBEAT_MS = 25_000;
const MAX_RECONNECT_MS = 10_000;
const MAX_RECONNECT_ATTEMPTS = 12;
const FATAL_CLOSE_CODES = new Set([1002, 1003, 1008, 1009]);

export default function useRoomSocket(roomCode) {
  const socketRef = useRef(null);
  const retryRef = useRef(null);
  const [status, setStatus] = useState('idle');
  const [snapshot, setSnapshot] = useState(null);
  const [lastEvent, setLastEvent] = useState(null);
  const [lastOfficialResult, setLastOfficialResult] = useState(null);
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
    setLastOfficialResult(null);
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

    function scheduleReconnect() {
      attempts += 1;
      if (attempts > MAX_RECONNECT_ATTEMPTS) {
        setStatus('error');
        setError('Could not reconnect to the room. Check the server and try again.');
        return;
      }
      setStatus('reconnecting');
      reconnectTimer = window.setTimeout(connect, Math.min(MAX_RECONNECT_MS, 1000 * 2 ** (attempts - 1)));
    }

    const client = new RoomSocket({
      onOpen: () => {
        if (!active) return;
        setStatus('synchronizing');
        setError('');
        clearInterval(heartbeatTimer);
        heartbeatTimer = window.setInterval(() => client.sendPing(), HEARTBEAT_MS);
      },
      onClose: (event) => {
        if (!active) return;
        clearInterval(heartbeatTimer);
        if (FATAL_CLOSE_CODES.has(event.code)) {
          const sessionExpired = event.code === 1008
            && /session|reconnect grace|room access/i.test(event.reason || '');
          setStatus(sessionExpired ? 'expired' : 'error');
          setSnapshot(null);
          setError(sessionExpired
            ? 'Your room session has ended. Create or join another room.'
            : event.code === 1008
              ? 'The room server closed this connection after a policy limit.'
              : 'The room connection is incompatible with this client.');
          client.close();
          return;
        }
        scheduleReconnect();
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
            setStatus('connected');
            attempts = 0;
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
          if (message.type === 'event') {
            setLastEvent(message);
            if (message.name === 'OfficialTestResult') setLastOfficialResult(message);
          }
          if (message.sequence > snapshotSequence + 1) setHasSequenceGap(true);
          requestLatest(client, message.sequence);
        } else if (message.type === 'error' && !message.request_id) {
          setError(message.message);
        }
      },
    });
    socketRef.current = client;
    retryRef.current = () => {
      if (client.disposed) {
        window.location.reload();
        return;
      }
      clearTimeout(reconnectTimer);
      attempts = 0;
      setError('');
      setStatus('reconnecting');
      connect();
    };

    function connect() {
      if (!active) return;
      try {
        client.connect();
      } catch {
        scheduleReconnect();
      }
    }
    connect();

    return () => {
      active = false;
      clearTimeout(reconnectTimer);
      clearInterval(heartbeatTimer);
      if (socketRef.current === client) socketRef.current = null;
      retryRef.current = null;
      client.close();
    };
  }, [roomCode]);

  const sendCommand = useCallback((action) => {
    const socket = socketRef.current;
    if (!socket) return Promise.reject(new RoomSocketError('NOT_CONNECTED', 'Waiting to connect to the room.'));
    return socket.sendCommand(action);
  }, []);

  const requestSnapshot = useCallback(() => socketRef.current?.requestSnapshot() ?? false, []);

  const retryConnection = useCallback(() => retryRef.current?.(), []);

  return { status, snapshot, lastEvent, lastOfficialResult, error, hasSequenceGap, sendCommand, requestSnapshot, retryConnection };
}
