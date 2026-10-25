import { createServer } from 'node:http';
import { WebSocketServer } from 'ws';
import * as Y from 'yjs';
import * as encoding from 'lib0/encoding';
import * as decoding from 'lib0/decoding';
import * as sync from 'y-protocols/sync';
import * as awarenessProtocol from 'y-protocols/awareness';
import {
  applyCandidateUpdate, createRestoreCandidate, loadPersistedDocument,
} from './document_state.mjs';

const PORT = Number(process.env.CODEMAFIA_EDITOR_PORT || 1234);
const HOST = process.env.CODEMAFIA_EDITOR_HOST || '127.0.0.1';
const API_BASE = (process.env.CODEMAFIA_API_INTERNAL_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
const SERVICE_KEY = process.env.CODEMAFIA_EDITOR_SERVICE_KEY;
const ORIGINS = new Set((process.env.CODEMAFIA_ALLOWED_ORIGINS || 'http://localhost:5173,http://127.0.0.1:5173')
  .split(',').map((item) => item.trim()).filter(Boolean));
const PREFIX = '/api/rooms/editor/ws/';
const MAX_MESSAGE = 262_144;
const documents = new Map();
const pendingDocuments = new Map();

if (!SERVICE_KEY || !Number.isInteger(PORT) || PORT < 1 || PORT > 65535) {
  throw new Error('Set CODEMAFIA_EDITOR_SERVICE_KEY and a valid CODEMAFIA_EDITOR_PORT.');
}

function send(socket, bytes) {
  if (socket.readyState !== socket.OPEN) return;
  if (socket.bufferedAmount > 1_000_000) {
    socket.close(4501, 'Editor client fell behind');
    return;
  }
  socket.send(bytes);
}

function syncPacket(write) {
  const encoder = encoding.createEncoder();
  encoding.writeVarUint(encoder, 0);
  write(encoder);
  return encoding.toUint8Array(encoder);
}

function awarenessPacket(awareness, ids) {
  const encoder = encoding.createEncoder();
  encoding.writeVarUint(encoder, 1);
  encoding.writeVarUint8Array(encoder, awarenessProtocol.encodeAwarenessUpdate(awareness, ids));
  return encoding.toUint8Array(encoder);
}

async function backend(path, cookie, body) {
  const response = await fetch(`${API_BASE}/api/rooms/editor/internal/${path}`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'x-editor-service-key': SERVICE_KEY,
      cookie,
    },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(5000),
  });
  if (!response.ok) {
    const error = new Error(`Editor authority rejected ${path}: ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

function newDocument(documentId, state) {
  const doc = loadPersistedDocument(state);
  return {
    documentId, doc, revisionId: state.revision_id,
    awareness: new awarenessProtocol.Awareness(doc),
    sockets: new Set(), clientOwners: new Map(), queue: Promise.resolve(),
  };
}

function broadcast(context, packet, except = null) {
  for (const socket of context.sockets) if (socket !== except) send(socket, packet);
}

async function acceptUpdate(context, socket, update) {
  const candidate = applyCandidateUpdate(context.doc, update);
  try {
    const { source, state: snapshot } = candidate;
    if (Buffer.byteLength(source, 'utf8') > 65_536 || snapshot.byteLength > MAX_MESSAGE) {
      socket.close(4400, 'Editor document is too large');
      return;
    }
    // An empty/replayed update needs no extra revision.
    if (Buffer.from(snapshot).equals(Buffer.from(Y.encodeStateAsUpdate(context.doc)))) return;
    const result = await backend('commit', socket.guestCookie, {
      document_id: context.documentId,
      previous_revision_id: context.revisionId,
      source,
      y_state: Buffer.from(snapshot).toString('base64'),
    });
    Y.applyUpdate(context.doc, update);
    context.revisionId = result.revision_id;
    broadcast(context, syncPacket((encoder) => sync.writeUpdate(encoder, update)), socket);
  } catch (error) {
    console.error('Editor update could not be committed:', error.status || 'internal error');
    if (error.status === 401 || error.status === 403) {
      socket.close(4403, 'Editor session is no longer authorized');
      return;
    }
    if (error.status === 413 || error.status === 422) {
      socket.close(4400, 'Editor document is invalid or too large');
      return;
    }
    // A failed commit must never become shared state. Reconnect reloads the
    // authoritative document and replays any locally retained Yjs changes.
    for (const peer of context.sockets) peer.close(4501, 'Editor state needs recovery');
    context.awareness.destroy();
    context.doc.destroy();
    documents.delete(context.documentId);
  } finally {
    candidate.doc.destroy();
  }
}

async function processMessage(context, socket, bytes) {
  if (bytes.byteLength > MAX_MESSAGE) {
    socket.close(4400, 'Message too large');
    return;
  }
  const decoder = decoding.createDecoder(new Uint8Array(bytes));
  const kind = decoding.readVarUint(decoder);
  if (kind === 0) {
    const subtype = decoding.readVarUint(decoder);
    if (subtype === sync.messageYjsSyncStep1) {
      await backend('authorize', socket.guestCookie, { document_id: context.documentId });
      const stateVector = decoding.readVarUint8Array(decoder);
      send(socket, syncPacket((encoder) => sync.writeSyncStep2(encoder, context.doc, stateVector)));
      return;
    }
    if (subtype === sync.messageYjsSyncStep2 || subtype === sync.messageYjsUpdate) {
      const update = decoding.readVarUint8Array(decoder);
      context.queue = context.queue.then(() => acceptUpdate(context, socket, update));
      return;
    }
  } else if (kind === 1) {
    // Code writes are checked by /internal/commit. Presence and read requests
    // need a fresh membership check because they do not create a revision.
    await backend('authorize', socket.guestCookie, { document_id: context.documentId });
    const update = decoding.readVarUint8Array(decoder);
    if (update.byteLength > 8192) {
      socket.close(4400, 'Awareness update too large');
      return;
    }
    const reader = decoding.createDecoder(update);
    const count = decoding.readVarUint(reader);
    if (count > 1) { socket.close(4400, 'Invalid awareness clients'); return; }
    for (let i = 0; i < count; i += 1) {
      const clientId = decoding.readVarUint(reader);
      decoding.readVarUint(reader); // awareness clock
      decoding.readVarString(reader); // encoded state
      const owner = context.clientOwners.get(clientId);
      if (owner && owner !== socket) { socket.close(4403, 'Awareness client is owned'); return; }
      context.clientOwners.set(clientId, socket);
      socket.clientIds.add(clientId);
      if (socket.clientIds.size > 1) { socket.close(4400, 'Too many awareness clients'); return; }
    }
    const safeUpdate = awarenessProtocol.modifyAwarenessUpdate(update, (state) => state === null ? null : ({
      selection: state?.selection ?? null,
      user: { id: socket.playerId, name: socket.displayName, color: '#73d5b3' },
    }));
    awarenessProtocol.applyAwarenessUpdate(context.awareness, safeUpdate, socket);
    broadcast(context, awarenessPacket(context.awareness, [...socket.clientIds]));
    return;
  } else if (kind === 3) {
    await backend('authorize', socket.guestCookie, { document_id: context.documentId });
    send(socket, awarenessPacket(context.awareness, [...context.awareness.getStates().keys()]));
    return;
  }
  socket.close(4400, 'Invalid editor message');
}

async function restore(context, cookie, revisionId) {
  const authority = await backend('authorize', cookie, { document_id: context.documentId });
  const target = authority.history.find((entry) => entry.revision_id === revisionId);
  if (!target) throw new Error('Revision is no longer in history.');
  const candidate = createRestoreCandidate(context.doc, target.source);
  try {
    const result = await backend('commit', cookie, {
      document_id: context.documentId,
      previous_revision_id: context.revisionId,
      source: target.source,
      y_state: Buffer.from(candidate.state).toString('base64'),
      restored_from_revision_id: revisionId,
    });
    Y.applyUpdate(context.doc, candidate.update);
    context.revisionId = result.revision_id;
    broadcast(context, syncPacket((encoder) => sync.writeUpdate(encoder, candidate.update)));
    return result.revision_id;
  } finally {
    candidate.doc.destroy();
  }
}

const server = createServer(async (request, response) => {
  if (request.url === '/health') {
    response.writeHead(200).end('ok');
    return;
  }
  if (request.url !== '/api/rooms/editor/restore'
    || !['POST', 'OPTIONS'].includes(request.method)) {
    response.writeHead(404).end();
    return;
  }
  const origin = request.headers.origin;
  if (!origin || !ORIGINS.has(origin)) {
    response.writeHead(403).end();
    return;
  }
  response.setHeader('access-control-allow-origin', origin);
  response.setHeader('access-control-allow-credentials', 'true');
  response.setHeader('access-control-allow-methods', 'POST, OPTIONS');
  response.setHeader('access-control-allow-headers', 'Content-Type');
  if (request.method === 'OPTIONS') {
    response.writeHead(204).end();
    return;
  }
  response.setHeader('content-type', 'application/json');
  try {
    let raw = '';
    for await (const chunk of request) {
      raw += chunk;
      if (raw.length > 1024) throw new Error('Restore request is too large.');
    }
    const { document_id: documentId, revision_id: revisionId } = JSON.parse(raw);
    if (typeof documentId !== 'string' || typeof revisionId !== 'string') throw new Error('Invalid restore request.');
    const cookie = request.headers.cookie || '';
    await backend('authorize', cookie, { document_id: documentId });
    const context = documents.get(documentId);
    if (!context) throw new Error('Editor is not connected.');
    const revision = await new Promise((resolve, reject) => {
      context.queue = context.queue.then(async () => resolve(await restore(context, cookie, revisionId))).catch(reject);
    });
    response.writeHead(200).end(JSON.stringify({ revision_id: revision }));
  } catch (error) {
    const status = error.status === 401 || error.status === 403 ? 403 : 409;
    response.writeHead(status).end(JSON.stringify({
      error: { code: 'RESTORE_FAILED', message: 'This revision could not be restored.' },
    }));
  }
});

const sockets = new WebSocketServer({ noServer: true, maxPayload: MAX_MESSAGE, perMessageDeflate: false });
async function getContext(documentId, cookie, authority) {
  let context = documents.get(documentId);
  if (context) return context;
  if (!pendingDocuments.has(documentId)) {
    const task = (async () => {
      let state = authority;
      let created = newDocument(documentId, state);
      if (!state.y_state) {
        try {
          await backend('initialize', cookie, {
            document_id: documentId,
            y_state: Buffer.from(Y.encodeStateAsUpdate(created.doc)).toString('base64'),
          });
        } catch {
          created.awareness.destroy();
          created.doc.destroy();
          state = await backend('authorize', cookie, { document_id: documentId });
          if (!state.y_state) throw new Error('Editor seed could not be persisted.');
          created = newDocument(documentId, state);
        }
      }
      documents.set(documentId, created);
      return created;
    })().finally(() => pendingDocuments.delete(documentId));
    pendingDocuments.set(documentId, task);
  }
  context = await pendingDocuments.get(documentId);
  return context;
}

server.on('upgrade', async (request, socket, head) => {
  const origin = request.headers.origin;
  let documentId = '';
  try {
    const parsed = new URL(request.url, 'http://localhost');
    if (parsed.search) throw new Error('Editor URL must not contain a query.');
    const pathname = parsed.pathname;
    documentId = pathname.startsWith(PREFIX) ? decodeURIComponent(pathname.slice(PREFIX.length)) : '';
  } catch {
    socket.write('HTTP/1.1 400 Bad Request\r\n\r\n');
    socket.destroy();
    return;
  }
  if (!origin || !ORIGINS.has(origin) || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,179}$/.test(documentId)) {
    socket.write('HTTP/1.1 403 Forbidden\r\n\r\n');
    socket.destroy();
    return;
  }
  try {
    const cookie = request.headers.cookie || '';
    const authority = await backend('authorize', cookie, { document_id: documentId });
    const context = await getContext(documentId, cookie, authority);
    if (context.revisionId !== authority.revision_id) {
      throw new Error('Editor revision changed outside this sync process.');
    }
    sockets.handleUpgrade(request, socket, head, (peer) => {
      peer.guestCookie = cookie;
      peer.playerId = authority.player_id;
      peer.displayName = authority.display_name;
      peer.clientIds = new Set();
      peer.isAlive = true;
      peer.messageCount = 0;
      context.sockets.add(peer);
      peer.on('pong', () => { peer.isAlive = true; });
      send(peer, syncPacket((encoder) => sync.writeSyncStep1(encoder, context.doc)));
      send(peer, awarenessPacket(context.awareness, [...context.awareness.getStates().keys()]));
      peer.on('message', (bytes) => {
        peer.messageCount += 1;
        if (peer.messageCount > 300) { peer.close(4400, 'Editor message rate exceeded'); return; }
        void processMessage(context, peer, bytes).catch((error) => {
          peer.close(error.status === 401 || error.status === 403 ? 4403 :
            error.status ? 4501 : 4400, 'Editor access or message is invalid');
        });
      });
      peer.on('close', () => {
        context.sockets.delete(peer);
        const removed = [...peer.clientIds];
        if (removed.length) {
          awarenessProtocol.removeAwarenessStates(context.awareness, removed, peer);
          for (const clientId of removed) context.clientOwners.delete(clientId);
          broadcast(context, awarenessPacket(context.awareness, removed));
        }
        if (context.sockets.size === 0) {
          context.queue.finally(() => {
            if (context.sockets.size === 0 && documents.get(documentId) === context) {
              documents.delete(documentId);
              context.awareness.destroy();
              context.doc.destroy();
            }
          });
        }
      });
    });
  } catch (error) {
    console.error('Editor connection denied:', error.status || 'internal error');
    sockets.handleUpgrade(request, socket, head, (peer) => {
      peer.close(error.status === 401 || error.status === 403 ? 4403 : 4501,
        'Editor access is unavailable');
    });
  }
});

const heartbeat = setInterval(() => {
  for (const peer of sockets.clients) {
    if (!peer.isAlive) { peer.terminate(); continue; }
    peer.isAlive = false;
    peer.messageCount = 0;
    peer.ping();
  }
}, 30_000);
heartbeat.unref();

server.listen(PORT, HOST, () => {
  console.log(`Editor sync listening on ${HOST}:${PORT}`);
});

export { server };

export async function closeEditorSync() {
  clearInterval(heartbeat);
  for (const peer of sockets.clients) peer.terminate();
  for (const context of documents.values()) {
    context.awareness.destroy();
    context.doc.destroy();
  }
  documents.clear();
  if (!server.listening) return;
  await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
}
