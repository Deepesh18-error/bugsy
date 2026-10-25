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
  disabled = false,
  disabledMessage = '',
}) {
  const generatedId = useId();
  const titleId = `${generatedId}-title`;
  const inputId = `${generatedId}-input`;
  const [draft, setDraft] = useState('');
  const [notice, setNotice] = useState('');
  const [sending, setSending] = useState(false);
  const [noticeStatus, setNoticeStatus] = useState('info');

  async function handleSubmit(event) {
    event.preventDefault();
    const text = draft.trim();

    if (!text) {
      setNotice('Write a message before sending.');
      setNoticeStatus('warning');
      return;
    }

    if (typeof onSendMessage !== 'function') {
      setNotice('Chat is unavailable right now.');
      setNoticeStatus('error');
      return;
    }

    if (disabled) {
      setNotice(disabledMessage || 'Chat is unavailable right now.');
      setNoticeStatus('warning');
      return;
    }
    if (sending) return;
    setSending(true);
    try {
      await onSendMessage(text);
      setDraft('');
      setNotice(isLive ? 'Message accepted by the server.' : 'Message added to this local preview.');
      setNoticeStatus('success');
    } catch (error) {
      setNotice(error.message || 'The message could not be sent.');
      setNoticeStatus('error');
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
        <div role="log" aria-label={`${title} messages`} aria-live="polite" aria-relevant="additions">
          <ol className={styles.messages}>
            {messages.map((message) => {
              const toneClass = styles[message.tone] ?? '';
              return (
                <li className={styles.message} key={message.id}>
                  <strong className={`${styles.messageName} ${toneClass}`}>
                    {message.name}{message.isYou ? ' · you' : ''}
                  </strong>
                  {message.sentAt && <time dateTime={message.sentAt} className={styles.sentAt}>
                    {Number.isFinite(Date.parse(message.sentAt))
                      ? `${new Date(message.sentAt).toLocaleTimeString([], {
                        timeZone: 'UTC', hour: '2-digit', minute: '2-digit', hour12: false,
                      })} UTC`
                      : 'Server time unavailable'}
                  </time>}
                  <p>{message.text}</p>
                </li>
              );
            })}
          </ol>
        </div>
      )}

      <form className={styles.form} onSubmit={handleSubmit}>
        <label className={styles.srOnly} htmlFor={inputId}>Write a chat message</label>
        <input
          id={inputId}
          maxLength={maxLength}
          disabled={sending || disabled}
          onChange={(event) => {
            setDraft(event.target.value);
            setNotice('');
            setNoticeStatus('info');
          }}
          placeholder={placeholder}
          value={draft}
          autoComplete="off"
        />
        <Button aria-label="Send message" size="small" variant="send" type="submit" disabled={sending || disabled}>
          {sending ? 'Sending…' : 'Send'}
        </Button>
      </form>

      <StatusMessage className={styles.notice} status={notice ? noticeStatus : disabled ? 'warning' : 'info'}>
        {notice || disabledMessage || messageStatus || localLabel}
      </StatusMessage>
    </Panel>
  );
}
