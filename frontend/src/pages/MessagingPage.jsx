import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faChevronLeft,
  faComments,
  faPen,
  faPaperPlane,
  faPhone,
  faSearch,
  faSpinner,
  faTrash,
  faUsers,
  faVideo,
} from '@fortawesome/free-solid-svg-icons';
import { apiUrl } from '../stores/configStore';
import './MessagingPage.css';

const POLL_INTERVAL = 8000;

function sameConversation(a, b) {
  if (!a || !b || a.type !== b.type) return false;
  if (a.type === 'group') return a.department === b.department;
  return a.partner_id === b.partner_id;
}

export default function MessagingPage({ user, token, onUnreadChange }) {
  const [users, setUsers] = useState([]);
  const [conversations, setConversations] = useState([]);
  const [selectedConversation, setSelectedConversation] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [search, setSearch] = useState('');
  const [sending, setSending] = useState(false);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [editingMessageId, setEditingMessageId] = useState(null);
  const [editingContent, setEditingContent] = useState('');
  const [mutatingMessageId, setMutatingMessageId] = useState(null);
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);
  const pollRef = useRef(null);

  const authHeaders = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);

  const updateUnreadBadge = useCallback((items) => {
    if (!onUnreadChange) return;
    onUnreadChange(items.reduce((sum, c) => sum + (c.unread_count || 0), 0));
  }, [onUnreadChange]);

  const fetchUsers = useCallback(async () => {
    try {
      const res = await fetch(apiUrl('/api/messaging/users'), { headers: authHeaders });
      if (res.ok) setUsers(await res.json());
    } catch {
      // keep existing user list on transient polling failures
    }
  }, [authHeaders]);

  const fetchConversations = useCallback(async () => {
    try {
      const res = await fetch(apiUrl('/api/messaging/conversations'), { headers: authHeaders });
      if (res.ok) {
        const data = await res.json();
        setConversations(data);
        updateUnreadBadge(data);
      }
    } catch {
      // keep existing conversation list on transient polling failures
    }
  }, [authHeaders, updateUnreadBadge]);

  const readEndpointFor = useCallback((conversation) => {
    if (!conversation) return null;
    if (conversation.type === 'group') {
      return `/api/messaging/groups/${encodeURIComponent(conversation.department)}/read`;
    }
    return `/api/messaging/conversations/${encodeURIComponent(conversation.partner_id)}/read`;
  }, []);

  const messagesEndpointFor = useCallback((conversation) => {
    if (!conversation) return null;
    if (conversation.type === 'group') {
      return `/api/messaging/groups/${encodeURIComponent(conversation.department)}/messages`;
    }
    return `/api/messaging/conversations/${encodeURIComponent(conversation.partner_id)}/messages`;
  }, []);

  const fetchMessages = useCallback(async (conversation, silent = false) => {
    const endpoint = messagesEndpointFor(conversation);
    if (!endpoint) return;
    if (!silent) setLoadingMessages(true);
    try {
      const res = await fetch(apiUrl(endpoint), { headers: authHeaders });
      if (res.ok) {
        setMessages(await res.json());
        const readEndpoint = readEndpointFor(conversation);
        if (readEndpoint) {
          fetch(apiUrl(readEndpoint), { method: 'POST', headers: authHeaders }).catch(() => {});
        }
      }
    } catch {
      // keep existing messages on transient polling failures
    } finally {
      if (!silent) setLoadingMessages(false);
    }
  }, [authHeaders, messagesEndpointFor, readEndpointFor]);

  useEffect(() => {
    fetchUsers();
    fetchConversations();
  }, [fetchUsers, fetchConversations]);

  useEffect(() => {
    if (selectedConversation) {
      fetchConversations();
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = setInterval(() => {
        fetchMessages(selectedConversation, true);
        fetchConversations();
      }, POLL_INTERVAL);
    } else if (pollRef.current) {
      clearInterval(pollRef.current);
    }

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [selectedConversation, fetchMessages, fetchConversations]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    if (selectedConversation) inputRef.current?.focus();
  }, [selectedConversation]);

  const directConversations = useMemo(() => {
    const byPartner = new Map(
      conversations
        .filter((c) => c.type === 'direct')
        .map((c) => [c.partner_id, c])
    );
    return users.map((u) => {
      const convo = byPartner.get(u.user_id);
      return {
        type: 'direct',
        conversation_id: convo?.conversation_id || `new:${u.user_id}`,
        partner_id: u.user_id,
        title: u.full_name || u.user_id,
        subtitle: [u.department, u.role].filter(Boolean).join(' · '),
        last_message: convo?.last_message || '',
        last_timestamp: convo?.last_timestamp || null,
        unread_count: convo?.unread_count || 0,
        user: u,
        hasHistory: Boolean(convo),
      };
    });
  }, [conversations, users]);

  const groupConversations = useMemo(
    () => conversations.filter((c) => c.type === 'group'),
    [conversations]
  );

  const filteredGroups = useMemo(() => {
    const term = search.trim().toLowerCase();
    return groupConversations.filter((c) => (
      !term ||
      c.title.toLowerCase().includes(term) ||
      (c.department || '').toLowerCase().includes(term)
    ));
  }, [groupConversations, search]);

  const filteredDirects = useMemo(() => {
    const term = search.trim().toLowerCase();
    const filtered = directConversations.filter((c) => (
      !term ||
      c.title.toLowerCase().includes(term) ||
      c.partner_id.toLowerCase().includes(term) ||
      (c.subtitle || '').toLowerCase().includes(term)
    ));
    return filtered.sort((a, b) => {
      if (a.hasHistory !== b.hasHistory) return a.hasHistory ? -1 : 1;
      return (b.last_timestamp || '').localeCompare(a.last_timestamp || '');
    });
  }, [directConversations, search]);

  const unreadTotal = conversations.reduce((sum, c) => sum + (c.unread_count || 0), 0);
  const hasResults = filteredGroups.length > 0 || filteredDirects.length > 0;

  const selectConversation = async (conversation) => {
    setSelectedConversation(conversation);
    setMessages([]);
    setInput('');
    setEditingMessageId(null);
    setEditingContent('');

    if (conversation.unread_count > 0 && onUnreadChange) {
      const newTotal = conversations.reduce(
        (sum, c) => sum + (sameConversation(c, conversation) ? 0 : (c.unread_count || 0)),
        0
      );
      onUnreadChange(newTotal);
    }

    await fetchMessages(conversation);
    fetchConversations();
  };

  const sendMessage = async () => {
    if (!input.trim() || !selectedConversation || sending) return;
    setSending(true);
    const content = input.trim();
    setInput('');

    try {
      const endpoint = messagesEndpointFor(selectedConversation);
      const res = await fetch(apiUrl(endpoint), {
        method: 'POST',
        headers: { ...authHeaders, 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
      });
      if (res.ok) {
        const msg = await res.json();
        setMessages((prev) => [...prev, msg]);
        fetchConversations();
      }
    } catch {
      setInput(content);
    } finally {
      setSending(false);
    }
  };

  const startEditMessage = (message) => {
    setEditingMessageId(message.id);
    setEditingContent(message.content || '');
  };

  const cancelEditMessage = () => {
    setEditingMessageId(null);
    setEditingContent('');
  };

  const saveEditMessage = async (messageId) => {
    const content = editingContent.trim();
    if (!content || mutatingMessageId) return;
    setMutatingMessageId(messageId);
    try {
      const res = await fetch(apiUrl(`/api/messaging/messages/${messageId}`), {
        method: 'PATCH',
        headers: { ...authHeaders, 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
      });
      if (res.ok) {
        const updated = await res.json();
        setMessages((prev) => prev.map((msg) => (msg.id === messageId ? updated : msg)));
        setEditingMessageId(null);
        setEditingContent('');
        fetchConversations();
      }
    } finally {
      setMutatingMessageId(null);
    }
  };

  const deleteMessage = async (messageId) => {
    if (mutatingMessageId) return;
    setMutatingMessageId(messageId);
    try {
      const res = await fetch(apiUrl(`/api/messaging/messages/${messageId}`), {
        method: 'DELETE',
        headers: authHeaders,
      });
      if (res.ok) {
        setMessages((prev) => prev.filter((msg) => msg.id !== messageId));
        if (editingMessageId === messageId) cancelEditMessage();
        fetchConversations();
      }
    } finally {
      setMutatingMessageId(null);
    }
  };

  const handleKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const formatTime = (iso) => {
    if (!iso) return '';
    const d = new Date(iso);
    const now = new Date();
    const diffDays = Math.floor((now - d) / 86400000);
    if (diffDays === 0) return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
    if (diffDays === 1) return 'Yesterday';
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  };

  const formatMsgTime = (iso) => {
    if (!iso) return '';
    return new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  };

  const getInitials = (name) => {
    if (!name) return '?';
    return name.split(' ').map((p) => p[0]).join('').toUpperCase().slice(0, 2);
  };

  const avatarColors = ['#6366f1', '#0ea5e9', '#ec4899', '#14b8a6', '#64748b', '#10b981', '#3b82f6', '#ef4444'];
  const getAvatarColor = (uid = '') => avatarColors[(uid.charCodeAt(0) || 0) % avatarColors.length];

  const selectedTitle = selectedConversation?.title || '';
  const selectedSubtitle = selectedConversation?.subtitle || '';
  const selectedIsGroup = selectedConversation?.type === 'group';

  return (
    <div className="messaging-shell">
      <aside className={`messaging-list ${selectedConversation ? 'has-selection' : ''}`}>
        <div className="messaging-list-header">
          <div className="messaging-title-row">
            <h2>Messages</h2>
            {unreadTotal > 0 && <span className="messaging-total-badge">{unreadTotal}</span>}
          </div>

          <label className="messaging-search">
            <FontAwesomeIcon icon={faSearch} />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search people or groups"
            />
          </label>
        </div>

        <div className="messaging-list-scroll">
          {filteredGroups.length > 0 && (
            <ConversationSection title="Groups">
              {filteredGroups.map((conversation) => (
                <ConversationRow
                  key={conversation.conversation_id}
                  conversation={conversation}
                  active={sameConversation(selectedConversation, conversation)}
                  onSelect={() => selectConversation(conversation)}
                  formatTime={formatTime}
                  getInitials={getInitials}
                  getAvatarColor={getAvatarColor}
                />
              ))}
            </ConversationSection>
          )}

          {filteredDirects.length > 0 && (
            <ConversationSection title={filteredGroups.length > 0 ? 'People' : 'People and Admins'}>
              {filteredDirects.map((conversation) => (
                <ConversationRow
                  key={conversation.conversation_id}
                  conversation={conversation}
                  active={sameConversation(selectedConversation, conversation)}
                  onSelect={() => selectConversation(conversation)}
                  formatTime={formatTime}
                  getInitials={getInitials}
                  getAvatarColor={getAvatarColor}
                />
              ))}
            </ConversationSection>
          )}

          {!hasResults && (
            <div className="messaging-empty-list">
              <FontAwesomeIcon icon={faComments} />
              <span>No conversations found</span>
            </div>
          )}
        </div>
      </aside>

      {selectedConversation ? (
        <section className="messaging-chat">
          <header className="messaging-chat-header">
            <button
              className="messaging-back-button"
              onClick={() => setSelectedConversation(null)}
              title="Back to conversations"
            >
              <FontAwesomeIcon icon={faChevronLeft} />
            </button>

            <ConversationAvatar
              conversation={selectedConversation}
              getInitials={getInitials}
              getAvatarColor={getAvatarColor}
              large
            />

            <div className="messaging-chat-heading">
              <div>{selectedTitle}</div>
              <span>{selectedSubtitle}</span>
            </div>

            <div className="messaging-call-actions" aria-label="Future call actions">
              <button type="button" title="Voice call - future scope" disabled>
                <FontAwesomeIcon icon={faPhone} />
              </button>
              <button type="button" title="Video call - future scope" disabled>
                <FontAwesomeIcon icon={faVideo} />
              </button>
            </div>
          </header>

          <div className="messaging-message-area">
            {loadingMessages ? (
              <div className="messaging-loader">
                <FontAwesomeIcon icon={faSpinner} spin />
              </div>
            ) : messages.length === 0 ? (
              <div className="messaging-empty-chat">
                <FontAwesomeIcon icon={selectedIsGroup ? faUsers : faComments} />
                <span>No messages yet</span>
              </div>
            ) : (
              <MessageBubbles
                messages={messages}
                currentUserId={user.user_id}
                formatMsgTime={formatMsgTime}
                getInitials={getInitials}
                getAvatarColor={getAvatarColor}
                selectedConversation={selectedConversation}
                editingMessageId={editingMessageId}
                editingContent={editingContent}
                setEditingContent={setEditingContent}
                mutatingMessageId={mutatingMessageId}
                onStartEdit={startEditMessage}
                onCancelEdit={cancelEditMessage}
                onSaveEdit={saveEditMessage}
                onDelete={deleteMessage}
              />
            )}
            <div ref={messagesEndRef} />
          </div>

          <footer className="messaging-input-bar">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKey}
              placeholder={`Message ${selectedTitle}`}
              rows={1}
              onInput={(e) => {
                e.target.style.height = 'auto';
                e.target.style.height = `${Math.min(e.target.scrollHeight, 120)}px`;
              }}
            />
            <button
              className="messaging-send-button"
              onClick={sendMessage}
              disabled={!input.trim() || sending}
              title="Send message"
            >
              {sending ? <FontAwesomeIcon icon={faSpinner} spin /> : <FontAwesomeIcon icon={faPaperPlane} />}
            </button>
          </footer>
        </section>
      ) : (
        <section className="messaging-empty-state">
          <div className="messaging-empty-icon">
            <FontAwesomeIcon icon={faComments} />
          </div>
          <div>
            <h3>Your Messages</h3>
            <p>Select a person or department group to start a conversation.</p>
          </div>
        </section>
      )}
    </div>
  );
}

function ConversationSection({ title, children }) {
  return (
    <section className="messaging-section">
      <div className="messaging-section-title">{title}</div>
      {children}
    </section>
  );
}

function ConversationRow({ conversation, active, onSelect, formatTime, getInitials, getAvatarColor }) {
  const preview = conversation.last_message
    ? `${conversation.type === 'group' && conversation.last_sender_name ? `${conversation.last_sender_name}: ` : ''}${conversation.last_message}`
    : conversation.subtitle || 'Start a conversation';

  return (
    <button className={`messaging-row ${active ? 'active' : ''}`} onClick={onSelect}>
      <ConversationAvatar
        conversation={conversation}
        getInitials={getInitials}
        getAvatarColor={getAvatarColor}
      />
      <span className="messaging-row-main">
        <span className="messaging-row-top">
          <span className="messaging-row-name">{conversation.title}</span>
          {conversation.last_timestamp && (
            <span className="messaging-row-time">{formatTime(conversation.last_timestamp)}</span>
          )}
        </span>
        <span className="messaging-row-bottom">
          <span className="messaging-row-preview">{preview}</span>
          {conversation.unread_count > 0 && (
            <span className="messaging-unread-badge">{conversation.unread_count}</span>
          )}
        </span>
      </span>
    </button>
  );
}

function ConversationAvatar({ conversation, getInitials, getAvatarColor, large = false }) {
  const className = `messaging-avatar ${large ? 'large' : ''} ${conversation.type === 'group' ? 'group' : ''}`;
  const colorKey = conversation.type === 'group' ? conversation.department : conversation.partner_id;

  return (
    <span className={className} style={{ '--avatar-color': getAvatarColor(colorKey || '') }}>
      {conversation.type === 'group'
        ? <FontAwesomeIcon icon={faUsers} />
        : getInitials(conversation.title)}
    </span>
  );
}

function MessageBubbles({
  messages,
  currentUserId,
  formatMsgTime,
  getInitials,
  getAvatarColor,
  selectedConversation,
  editingMessageId,
  editingContent,
  setEditingContent,
  mutatingMessageId,
  onStartEdit,
  onCancelEdit,
  onSaveEdit,
  onDelete,
}) {
  const groups = [];
  for (const msg of messages) {
    const isMine = msg.sender_id === currentUserId;
    const lastGroup = groups[groups.length - 1];
    if (!lastGroup || lastGroup.isMine !== isMine || lastGroup.senderId !== msg.sender_id) {
      groups.push({ isMine, senderId: msg.sender_id, senderName: msg.sender_name, msgs: [msg] });
    } else {
      lastGroup.msgs.push(msg);
    }
  }

  return (
    <>
      {groups.map((group, index) => {
        const label = group.senderName || selectedConversation.title;
        return (
          <div key={`${group.senderId}-${index}`} className={`message-group ${group.isMine ? 'mine' : ''}`}>
            {!group.isMine && (
              <div className="message-sender">
                <span className="message-sender-avatar" style={{ '--avatar-color': getAvatarColor(group.senderId || '') }}>
                  {getInitials(label)}
                </span>
                <span>{label}</span>
              </div>
            )}

            <div className="message-stack">
              {group.msgs.map((msg, messageIndex) => (
                <MessageBubble
                  key={msg.id || messageIndex}
                  msg={msg}
                  isMine={group.isMine}
                  isEditing={editingMessageId === msg.id}
                  editingContent={editingContent}
                  setEditingContent={setEditingContent}
                  isMutating={mutatingMessageId === msg.id}
                  formatMsgTime={formatMsgTime}
                  onStartEdit={onStartEdit}
                  onCancelEdit={onCancelEdit}
                  onSaveEdit={onSaveEdit}
                  onDelete={onDelete}
                />
              ))}
              <div className="message-time">
                {formatMsgTime(group.msgs[group.msgs.length - 1].timestamp)}
              </div>
            </div>
          </div>
        );
      })}
    </>
  );
}

function MessageBubble({
  msg,
  isMine,
  isEditing,
  editingContent,
  setEditingContent,
  isMutating,
  formatMsgTime,
  onStartEdit,
  onCancelEdit,
  onSaveEdit,
  onDelete,
}) {
  const handleEditKey = (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      onSaveEdit(msg.id);
    }
    if (event.key === 'Escape') {
      onCancelEdit();
    }
  };

  return (
    <div className={`message-item ${isMine ? 'mine' : ''}`}>
      {isEditing ? (
        <div className="message-edit-panel">
          <textarea
            value={editingContent}
            onChange={(event) => setEditingContent(event.target.value)}
            onKeyDown={handleEditKey}
            rows={2}
            autoFocus
          />
          <div className="message-edit-actions">
            <button type="button" onClick={() => onSaveEdit(msg.id)} disabled={!editingContent.trim() || isMutating}>
              Save
            </button>
            <button type="button" onClick={onCancelEdit} disabled={isMutating}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <>
          {isMine && (
            <span className="message-actions">
              <button type="button" title="Edit message" onClick={() => onStartEdit(msg)} disabled={isMutating}>
                <FontAwesomeIcon icon={faPen} />
              </button>
              <button type="button" title="Delete message" onClick={() => onDelete(msg.id)} disabled={isMutating}>
                <FontAwesomeIcon icon={isMutating ? faSpinner : faTrash} spin={isMutating} />
              </button>
            </span>
          )}
          <div className="message-bubble" title={formatMsgTime(msg.timestamp)}>
            {msg.content}
            {msg.edited && <span className="message-edited-label">edited</span>}
          </div>
        </>
      )}
    </div>
  );
}
