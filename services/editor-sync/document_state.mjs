import * as Y from 'yjs';

export function loadPersistedDocument(state) {
  const doc = new Y.Doc();
  if (state.y_state) Y.applyUpdate(doc, Buffer.from(state.y_state, 'base64'));
  else doc.getText('source').insert(0, state.source);
  if (doc.getText('source').toString() !== state.source) {
    doc.destroy();
    throw new Error('Persisted editor source and Yjs state disagree.');
  }
  return doc;
}

export function applyCandidateUpdate(current, update) {
  const candidate = new Y.Doc();
  Y.applyUpdate(candidate, Y.encodeStateAsUpdate(current));
  Y.applyUpdate(candidate, update);
  return {
    doc: candidate,
    source: candidate.getText('source').toString(),
    state: Y.encodeStateAsUpdate(candidate),
  };
}

export function createRestoreCandidate(current, source) {
  const candidate = new Y.Doc();
  Y.applyUpdate(candidate, Y.encodeStateAsUpdate(current));
  const text = candidate.getText('source');
  candidate.transact(() => {
    text.delete(0, text.length);
    text.insert(0, source);
  });
  return {
    doc: candidate,
    update: Y.encodeStateAsUpdate(candidate, Y.encodeStateVector(current)),
    state: Y.encodeStateAsUpdate(candidate),
  };
}
