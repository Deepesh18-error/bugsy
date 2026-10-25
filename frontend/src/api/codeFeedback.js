const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');

export class CodeFeedbackError extends Error {
  constructor(code, message) {
    super(message);
    this.name = 'CodeFeedbackError';
    this.code = code;
  }
}

const isText = (value) => typeof value === 'string' && value.length > 0;

/** Public cases are advisory. Hidden and official tests never enter this bundle. */
export async function loadPublicFeedbackBundle(roomCode, roundNumber, signal) {
  if (!isText(roomCode) || !Number.isInteger(roundNumber) || roundNumber < 1 || roundNumber > 4) {
    throw new CodeFeedbackError('INVALID_INPUT', 'A valid room and round are required.');
  }
  let response;
  try {
    response = await fetch(`${API_BASE_URL}/api/rooms/feedback/bundle`, {
      method: 'POST',
      credentials: 'include',
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ room_code: roomCode, round_number: roundNumber }),
      signal,
    });
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new CodeFeedbackError('NETWORK_ERROR', 'Could not load browser feedback checks.');
  }
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new CodeFeedbackError('INVALID_RESPONSE', 'The feedback service returned unreadable data.');
  }
  if (!response.ok) {
    throw new CodeFeedbackError(payload?.error?.code || 'FEEDBACK_UNAVAILABLE',
      payload?.error?.message || 'Browser feedback is unavailable.');
  }
  if (!isText(payload?.challenge_id) || !isText(payload?.challenge_version)
    || !isText(payload?.source_revision_id) || payload.provisional_only !== true
    || !Array.isArray(payload.tests) || payload.tests.length === 0 || payload.tests.length > 16
    || payload.tests.some((test) => !isText(test?.test_id)
      || !isText(test?.name) || !isText(test?.test_code)
      || !isText(test?.failure_message)
      || typeof test.required_for_civilian_win !== 'boolean')) {
    throw new CodeFeedbackError('INVALID_RESPONSE', 'The browser feedback bundle is incompatible.');
  }
  return payload;
}

/** The server resolves this revision to saved source; no browser code is sent. */
export function requestOfficialTestRun(sendCommand, sourceRevisionId) {
  if (!isText(sourceRevisionId)) {
    return Promise.reject(new CodeFeedbackError('NO_REVISION', 'Wait for the server to save a code revision.'));
  }
  return sendCommand({ name: 'request_official_test_run', source_revision_id: sourceRevisionId });
}
