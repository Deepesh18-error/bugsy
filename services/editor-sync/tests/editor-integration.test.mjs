import test from 'node:test';
import assert from 'node:assert/strict';
import * as Y from 'yjs';
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
