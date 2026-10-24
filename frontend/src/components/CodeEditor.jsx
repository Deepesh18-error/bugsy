import { useEffect, useId, useRef, useState } from 'react';
import * as monaco from 'monaco-editor/editor/editor.api.js';
import 'monaco-editor/languages/definitions/python/register.js';
import EditorWorker from 'monaco-editor/editor/editor.worker.js?worker';
import { MonacoBinding } from 'y-monaco';
import styles from '../styles/components/CodeEditor.module.css';

// Vite bundles Monaco's worker separately. Python uses Monaco's basic language
// support; this worker provides the editor's core background services.
self.MonacoEnvironment = {
  getWorker: () => new EditorWorker(),
};

function applyTextChange(sharedText, previous, next) {
  if (previous === next) return;

  let start = 0;
  while (start < previous.length && start < next.length && previous[start] === next[start]) {
    start += 1;
  }
  let oldEnd = previous.length;
  let newEnd = next.length;
  while (oldEnd > start && newEnd > start && previous[oldEnd - 1] === next[newEnd - 1]) {
    oldEnd -= 1;
    newEnd -= 1;
  }

  // The accessible fallback changes only the affected range rather than
  // replacing the entire shared document on every keystroke.
  sharedText.doc.transact(() => {
    if (oldEnd > start) sharedText.delete(start, oldEnd - start);
    if (newEnd > start) sharedText.insert(start, next.slice(start, newEnd));
  }, 'accessible-editor');
}

export default function CodeEditor({
  sharedText,
  awareness,
  canEdit = false,
  label = 'Shared Python code',
  preferAccessibleEditor = false,
}) {
  const containerRef = useRef(null);
  const editorRef = useRef(null);
  const helpId = useId();
  const [plainText, setPlainText] = useState(() => sharedText?.toString() ?? '');

  useEffect(() => {
    if (!sharedText || !preferAccessibleEditor) {
      setPlainText('');
      return undefined;
    }
    const update = () => setPlainText(sharedText.toString());
    update();
    sharedText.observe(update);
    return () => sharedText.unobserve(update);
  }, [sharedText, preferAccessibleEditor]);

  useEffect(() => {
    if (!sharedText || preferAccessibleEditor || !containerRef.current) return undefined;

    const model = monaco.editor.createModel(sharedText.toString(), 'python');
    const editor = monaco.editor.create(containerRef.current, {
      model,
      theme: 'vs-dark',
      automaticLayout: true,
      minimap: { enabled: false },
      scrollBeyondLastLine: false,
      fontFamily: 'Cascadia Mono, Consolas, monospace',
      fontSize: 14,
      tabSize: 4,
      ariaLabel: label,
      readOnly: !canEdit,
    });
    const binding = new MonacoBinding(
      sharedText,
      model,
      new Set([editor]),
      awareness ?? undefined,
    );
    editorRef.current = editor;

    return () => {
      editorRef.current = null;
      binding.destroy();
      editor.dispose();
      model.dispose();
    };
  }, [sharedText, awareness, preferAccessibleEditor, label]);

  useEffect(() => {
    editorRef.current?.updateOptions({ readOnly: !canEdit });
  }, [canEdit]);

  if (!sharedText) {
    return <p className={styles.waiting} role="status">Waiting for the shared document…</p>;
  }

  return (
    <div className={styles.wrapper}>
      {preferAccessibleEditor ? (
        <textarea
          className={styles.textarea}
          aria-label={label}
          aria-describedby={helpId}
          value={plainText}
          readOnly={!canEdit}
          spellCheck={false}
          onChange={(event) => applyTextChange(sharedText, sharedText.toString(), event.target.value)}
        />
      ) : (
        <div ref={containerRef} className={styles.monaco} aria-label={label} />
      )}
      <p id={helpId} className={styles.help}>
        {canEdit ? 'Changes are shared with this round.' : 'Editing is available after the document connects and the round opens.'}
      </p>
    </div>
  );
}
