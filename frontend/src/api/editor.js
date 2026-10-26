import { SERVER_CATEGORY_IDS } from './rooms.js';
import { API_BASE_URL } from './baseUrl.js';

const EDITOR_SESSION_PATH = '/api/rooms/editor/session';
const EDITOR_HISTORY_PATH = '/api/rooms/editor/history';

export class EditorApiError extends Error {
  constructor(code, message) {
    super(message);
    this.name = 'EditorApiError';
    this.code = code;
  }
}

function isRecord(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function hasOnlyKeys(value, allowed) {
  return Object.keys(value).every((key) => allowed.includes(key));
}

function nonBlank(value) {
  return typeof value === 'string' && value.trim().length > 0;
}

function requireEditorSocketUrl(value) {
  let url;
  try {
    url = new URL(value);
  } catch {
    throw new EditorApiError('INVALID_RESPONSE', 'The editor server returned an invalid connection address.');
  }
  const apiUrl = new URL(API_BASE_URL);
  if (!['ws:', 'wss:'].includes(url.protocol)
    || url.hostname !== apiUrl.hostname
    || (apiUrl.protocol === 'https:' && url.protocol !== 'wss:')
    || url.pathname !== '/api/rooms/editor/ws'
    || url.username || url.password || url.search || url.hash) {
    throw new EditorApiError('INVALID_RESPONSE', 'The editor server returned an unsafe connection address.');
  }
  return url.toString();
}

/**
 * Future FastAPI contract: POST /api/rooms/editor/session, authenticated by
 * the existing HTTP-only guest cookie. No credential goes in the URL or JSON.
 * The backend must scope document_id to the authenticated room/match/round.
 * This client is intentionally unused until that endpoint is implemented.
 */
export async function loadEditorSession(roomCode, roundNumber) {
  if (!nonBlank(roomCode) || !Number.isInteger(roundNumber) || roundNumber < 1 || roundNumber > 4) {
    throw new EditorApiError('INVALID_INPUT', 'A valid room and round are required to open the editor.');
  }

  let response;
  try {
    response = await fetch(`${API_BASE_URL}${EDITOR_SESSION_PATH}`, {
      method: 'POST',
      credentials: 'include',
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ room_code: roomCode, round_number: roundNumber }),
    });
  } catch {
    throw new EditorApiError('NETWORK_ERROR', 'Cannot reach the editor session service.');
  }

  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new EditorApiError('INVALID_RESPONSE', 'The editor server returned an unreadable response.');
  }
  if (!response.ok) {
    throw new EditorApiError(
      payload?.error?.code || 'REQUEST_FAILED',
      payload?.error?.message || 'The shared editor is not available for this round.',
    );
  }

  const challenge = payload?.challenge;
  if (!isRecord(payload)
    || !hasOnlyKeys(payload, ['room_code', 'round_number', 'document_id', 'websocket_url', 'challenge'])
    || payload.room_code !== roomCode
    || payload.round_number !== roundNumber
    || typeof payload.document_id !== 'string'
    || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,179}$/.test(payload.document_id)
    || !isRecord(challenge)
    || !hasOnlyKeys(challenge, ['id', 'version', 'category', 'title', 'prompt', 'starter_code'])
    || !nonBlank(challenge.id)
    || !nonBlank(challenge.version)
    || !SERVER_CATEGORY_IDS.includes(challenge.category)
    || !nonBlank(challenge.title)
    || !nonBlank(challenge.prompt)
    || !nonBlank(challenge.starter_code)) {
    throw new EditorApiError('INVALID_RESPONSE', 'The editor server returned incompatible challenge data.');
  }

  return {
    roomCode: payload.room_code,
    roundNumber: payload.round_number,
    documentId: payload.document_id,
    websocketUrl: requireEditorSocketUrl(payload.websocket_url),
    challenge: {
      id: challenge.id,
      version: challenge.version,
      category: challenge.category,
      title: challenge.title,
      prompt: challenge.prompt,
      starterCode: challenge.starter_code,
    },
  };
}

export async function loadEditorHistory(documentId) {
  const response = await fetch(`${API_BASE_URL}${EDITOR_HISTORY_PATH}`, {
    method: 'POST', credentials: 'include', cache: 'no-store',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ document_id: documentId }),
  });
  const payload = await response.json();
  if (!response.ok) throw new EditorApiError(payload?.error?.code || 'HISTORY_FAILED',
    payload?.error?.message || 'Could not load revision history.');
  if (!Array.isArray(payload.history)) throw new EditorApiError('INVALID_RESPONSE', 'Invalid revision history.');
  return payload.history;
}

export async function restoreEditorRevision(session, revisionId) {
  const url = new URL(session.websocketUrl);
  url.protocol = url.protocol === 'wss:' ? 'https:' : 'http:';
  url.pathname = '/api/rooms/editor/restore';
  const response = await fetch(url, {
    method: 'POST', credentials: 'include', cache: 'no-store',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ document_id: session.documentId, revision_id: revisionId }),
  });
  const payload = await response.json();
  if (!response.ok) throw new EditorApiError(payload?.error?.code || 'RESTORE_FAILED',
    payload?.error?.message || 'Could not restore this revision.');
  return payload.revision_id;
}
