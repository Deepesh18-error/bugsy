import { useEffect, useState } from 'react';
import * as Y from 'yjs';
import { WebsocketProvider } from 'y-websocket';

const EMPTY_EDITOR = Object.freeze({
  documentId: null,
  sharedText: null,
  awareness: null,
  status: 'idle',
  error: '',
});

/**
 * One Yjs document and provider per authorized room/match/round document.
 * The provider handles reconnects; a new document ID tears down the old one.
 * A sync event means clients agree on text, not that a durable save was acked.
 */
export default function useCollaborativeEditor(session, participant, enabled = true) {
  const [editor, setEditor] = useState(EMPTY_EDITOR);
  const documentId = session?.documentId;
  const websocketUrl = session?.websocketUrl;
  const playerId = participant?.id;
  const playerName = participant?.name;
  const playerColor = participant?.color;

  useEffect(() => {
    if (!enabled || !documentId || !websocketUrl) return undefined;

    let active = true;
    let accessRevoked = false;
    const doc = new Y.Doc();
    const sharedText = doc.getText('source');
    const provider = new WebsocketProvider(websocketUrl, documentId, doc, {
      connect: false,
      disableBc: true,
    });

    // Awareness is decorative and may be supplied by a client. The editor
    // service must authenticate the socket independently of these fields.
    if (playerId && playerName) {
      provider.awareness.setLocalStateField('user', {
        id: playerId,
        name: playerName,
        color: playerColor ?? '#73d5b3',
      });
    }

    const update = (status, error = '') => {
      if (!active) return;
      setEditor({
        documentId,
        sharedText,
        awareness: provider.awareness,
        status,
        error,
      });
    };
    const onStatus = ({ status }) => {
      if (accessRevoked) return;
      update(status === 'connected' && provider.synced ? 'synced' : status);
    };
    const onSync = (synced) => {
      if (accessRevoked) return;
      update(synced ? 'synced' : 'connecting');
    };
    const onClose = (event) => {
      if (event?.code >= 4400 && event.code < 4500) {
        accessRevoked = true;
        update('error', 'Editor access ended. Refresh the room to check your session.');
      } else {
        update('disconnected');
      }
    };
    const onError = () => {
      if (accessRevoked) return;
      update('disconnected', 'The shared editor connection was interrupted. Reconnecting…');
    };

    provider.on('status', onStatus);
    provider.on('sync', onSync);
    provider.on('connection-close', onClose);
    provider.on('connection-error', onError);
    update('connecting');
    provider.connect();

    return () => {
      active = false;
      provider.off('status', onStatus);
      provider.off('sync', onSync);
      provider.off('connection-close', onClose);
      provider.off('connection-error', onError);
      provider.destroy();
      doc.destroy();
    };
  }, [enabled, documentId, websocketUrl, playerId, playerName, playerColor]);

  // Do not expose the previous round's document during the render before its
  // effect cleanup runs. A round change must not briefly show stale code.
  if (!enabled || editor.documentId !== documentId) {
    return { ...EMPTY_EDITOR, canEdit: false };
  }
  return { ...editor, canEdit: editor.status === 'synced' };
}
