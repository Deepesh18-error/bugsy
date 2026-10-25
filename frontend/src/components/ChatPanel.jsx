import { useId, useState } from 'react';
import Button from './Button.jsx';
import Panel from './Panel.jsx';
import StatusMessage from './StatusMessage.jsx';
import styles from '../styles/components/ChatPanel.module.css';

export default function ChatPanel({
  messages = [],
  onSendMessage,
  title = 'Chat',
  eyebrow = 'TEAM CHANNEL',
  emptyMessage = 'No messages yet. Start the conversation.',
  placeholder = 'Write a message…',
  localLabel = 'LOCAL PREVIEW · MESSAGES ARE NOT SHARED',
  maxLength = 180,
  className = '',
  messageStatus = '',
  isLive = false,
}) {
  const generatedId = useId();
  const titleId = `${generatedId}-title`;
  const inputId = `${generatedId}-input`;
  const [draft, setDraft] = useState('');
  const [notice, setNotice] = useState('');
  const [sending, setSending] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    const text = draft.trim();

    if (!text) {
      setNotice('Write a message before sending.');
      return;
    }

    if (typeof onSendMessage !== 'function') {
      setNotice('Chat is unavailable right now.');
      return;
    }

    if (sending) return;
    setSending(true);
    try {
      await onSendMessage(text);
      setDraft('');
      setNotice(isLive ? 'Message accepted by the server.' : 'Message added to this local preview.');
    } catch (error) {
      setNotice(error.message || 'The message could not be sent.');
    } finally {
      setSending(false);
    }
  }

  return (
    <Panel className={`${styles.panel} ${className}`.trim()} aria-labelledby={titleId}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>{eyebrow}</p>
          <h2 id={titleId}>{title}</h2>
        </div>
        <span className={styles.localTag}>{isLive ? 'LIVE' : 'LOCAL'}</span>
      </header>

      {messages.length === 0 ? (
        <div className={styles.emptyState}>
          <span aria-hidden="true">···</span>
          <p>{emptyMessage}</p>
        </div>
      ) : (
        <ol className={styles.messages} aria-label={`${title} messages`} aria-live="polite" aria-relevant="additions">
          {messages.map((message) => {
            const toneClass = styles[message.tone] ?? '';
            return (
              <li className={styles.message} key={message.id}>
                <strong className={`${styles.messageName} ${toneClass}`}>
                  {message.name}{message.isYou ? ' · you' : ''}
                </strong>
                <p>{message.text}</p>
              </li>
            );
          })}
        </ol>
      )}

      <form className={styles.form} onSubmit={handleSubmit}>
        <label className={styles.srOnly} htmlFor={inputId}>Write a chat message</label>
        <input
          id={inputId}
          maxLength={maxLength}
          disabled={sending}
          onChange={(event) => {
            setDraft(event.target.value);
            setNotice('');
          }}
          placeholder={placeholder}
          value={draft}
          autoComplete="off"
        />
        <Button aria-label="Send message" size="small" variant="send" type="submit" disabled={sending}>
          {sending ? 'Sending…' : 'Send'}
        </Button>
      </form>

      <StatusMessage className={styles.notice} status="info">
        {notice || messageStatus || localLabel}
      </StatusMessage>
    </Panel>
  );
}
