import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { once } from 'node:events';
import WebSocket from 'ws';
import * as Y from 'yjs';
import * as encoding from 'lib0/encoding';
import * as sync from 'y-protocols/sync';
import {
  applyCandidateUpdate, createRestoreCandidate, loadPersistedDocument,
} from '../document_state.mjs';

function clientFrom(state) {
  return loadPersistedDocument({ source: state.source,
    y_state: Buffer.from(Y.encodeStateAsUpdate(state.doc)).toString('base64') });
}

test('concurrent Yjs updates converge, persist, restore, and recover', () => {
  const authority = { doc: loadPersistedDocument({ source: 'abc', y_state: null }), source: 'abc' };
  const first = clientFrom(authority);
  const second = clientFrom(authority);
  const acceptedSources = [];
  try {
    let firstUpdate;
    first.on('update', (update) => { firstUpdate = update; });
    first.getText('source').insert(3, 'A');
    const localFirstUpdate = firstUpdate;
    let secondUpdate;
    second.on('update', (update) => { secondUpdate = update; });
    second.getText('source').insert(3, 'B');
    const localSecondUpdate = secondUpdate;

    for (const update of [localFirstUpdate, localSecondUpdate]) {
      const candidate = applyCandidateUpdate(authority.doc, update);
      acceptedSources.push(candidate.source);
      Y.applyUpdate(authority.doc, update);
      candidate.doc.destroy();
    }
    Y.applyUpdate(first, localSecondUpdate);
    Y.applyUpdate(second, localFirstUpdate);
    authority.source = authority.doc.getText('source').toString();
    assert.equal(first.getText('source').toString(), authority.source);
    assert.equal(second.getText('source').toString(), authority.source);
    assert.match(authority.source, /A/);
    assert.match(authority.source, /B/);

    const persisted = {
      source: authority.source,
      y_state: Buffer.from(Y.encodeStateAsUpdate(authority.doc)).toString('base64'),
    };
    const afterRestart = loadPersistedDocument(persisted);
    assert.equal(afterRestart.getText('source').toString(), authority.source);

    const restore = createRestoreCandidate(afterRestart, acceptedSources[0]);
    Y.applyUpdate(afterRestart, restore.update);
    Y.applyUpdate(first, restore.update);
    Y.applyUpdate(second, restore.update);
    assert.equal(afterRestart.getText('source').toString(), acceptedSources[0]);
    assert.equal(first.getText('source').toString(), acceptedSources[0]);
    assert.equal(second.getText('source').toString(), acceptedSources[0]);
    restore.doc.destroy();
    afterRestart.destroy();
  } finally {
    authority.doc.destroy();
    first.destroy();
    second.destroy();
  }
});

test('recovery rejects source and Yjs state disagreement', () => {
  const doc = new Y.Doc();
  doc.getText('source').insert(0, 'stored text');
  const yState = Buffer.from(Y.encodeStateAsUpdate(doc)).toString('base64');
  doc.destroy();
  assert.throws(() => loadPersistedDocument({ source: 'different text', y_state: yState }),
    /source and Yjs state disagree/);
});

test('editor socket binds its cookie to the current room document and rejects stale writes', async () => {
  const documentId = 'TEST42:match-a:1';
  const source = 'class Counter: pass\n';
  const initial = loadPersistedDocument({ source, y_state: null });
  const yState = Buffer.from(Y.encodeStateAsUpdate(initial)).toString('base64');
  initial.destroy();
  let activeDocumentId = documentId;
  let commitAttempts = 0;
  const authority = createServer(async (request, response) => {
    let raw = '';
    for await (const chunk of request) raw += chunk;
    const payload = JSON.parse(raw);
    const permitted = request.headers['x-editor-service-key'] === 'test-service-key'
      && request.headers.cookie === 'codemafia_guest=player-one'
      && payload.document_id === activeDocumentId;
    if (request.url.endsWith('/commit')) commitAttempts += 1;
    response.setHeader('content-type', 'application/json');
    if (!permitted) {
      response.writeHead(403).end(JSON.stringify({ error: { code: 'EDITOR_FORBIDDEN' } }));
      return;
    }
    if (request.url.endsWith('/authorize')) {
      response.writeHead(200).end(JSON.stringify({
        player_id: 'p1', display_name: 'Ada', revision_id: 'seed-a', source,
        y_state: yState, history: [],
      }));
      return;
    }
    response.writeHead(200).end(JSON.stringify({ revision_id: 'revision-b' }));
  });
  authority.listen(0, '127.0.0.1');
  await once(authority, 'listening');

  // The sync service reads these settings at import time. Node's test files
  // run in separate processes, so this does not change other test fixtures.
  const reservation = createServer().listen(0, '127.0.0.1');
  await once(reservation, 'listening');
  const editorPort = reservation.address().port;
  await new Promise((resolve) => reservation.close(resolve));
  process.env.CODEMAFIA_EDITOR_PORT = String(editorPort);
  process.env.CODEMAFIA_API_INTERNAL_URL = `http://127.0.0.1:${authority.address().port}`;
  process.env.CODEMAFIA_EDITOR_SERVICE_KEY = 'test-service-key';
  const editor = await import('../server.mjs');
  if (!editor.server.listening) await once(editor.server, 'listening');

  const connect = (id, cookie) => new WebSocket(
    `ws://127.0.0.1:${editorPort}/api/rooms/editor/ws/${id}`,
    { headers: { Origin: 'http://127.0.0.1:5173', Cookie: cookie } },
  );
  try {
    for (const [id, cookie] of [
      [documentId, 'codemafia_guest=other-player'],
      ['TEST42:guessed-match:1', 'codemafia_guest=player-one'],
    ]) {
      const rejected = connect(id, cookie);
      const [code] = await once(rejected, 'close');
      assert.equal(code, 4403);
    }

    const valid = connect(documentId, 'codemafia_guest=player-one');
    const presence = connect(documentId, 'codemafia_guest=player-one');
    await Promise.all([once(valid, 'open'), once(presence, 'open')]);
    activeDocumentId = 'TEST42:match-a:2';
    const restore = await fetch(`http://127.0.0.1:${editorPort}/api/rooms/editor/restore`, {
      method: 'POST',
      headers: { Origin: 'http://127.0.0.1:5173', Cookie: 'codemafia_guest=player-one',
        'Content-Type': 'application/json' },
      body: JSON.stringify({ document_id: documentId, revision_id: 'old-revision' }),
    });
    assert.equal(restore.status, 403);
    assert.deepEqual(await restore.json(), {
      error: { code: 'RESTORE_FAILED', message: 'This revision could not be restored.' },
    });
    const awarenessRequest = encoding.createEncoder();
    encoding.writeVarUint(awarenessRequest, 3);
    presence.send(encoding.toUint8Array(awarenessRequest));
    const [presenceCode] = await once(presence, 'close');
    assert.equal(presenceCode, 4403);
    const client = loadPersistedDocument({ source, y_state: yState });
    let update;
    client.on('update', (bytes) => { update = bytes; });
    client.getText('source').insert(source.length, '# old round write\n');
    const packet = encoding.createEncoder();
    encoding.writeVarUint(packet, 0);
    encoding.writeVarUint(packet, sync.messageYjsUpdate);
    encoding.writeVarUint8Array(packet, update);
    valid.send(encoding.toUint8Array(packet));
    const [code] = await once(valid, 'close');
    assert.equal(code, 4403);
    assert.equal(commitAttempts, 1);
    client.destroy();
  } finally {
    await editor.closeEditorSync();
    await new Promise((resolve) => authority.close(resolve));
  }
});
