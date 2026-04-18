import React, { useState, useEffect, useRef, useCallback } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faSearch, faPaperPlane, faUser, faComments,
  faCircle, faSpinner, faChevronLeft
} from '@fortawesome/free-solid-svg-icons';
import { apiUrl } from '../stores/configStore';

const POLL_INTERVAL = 8000; // 8 seconds

export default function MessagingPage({ user, token, onUnreadChange }) {
  const [users, setUsers] = useState([]);
  const [conversations, setConversations] = useState([]);
  const [selectedUser, setSelectedUser] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [search, setSearch] = useState('');
  const [sending, setSending] = useState(false);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);
  const pollRef = useRef(null);

  const authHeaders = { Authorization: `Bearer ${token}` };

  // ── Fetch all chattable users ──
  const fetchUsers = useCallback(async () => {
    try {
      const res = await fetch(apiUrl('/api/messaging/users'), { headers: authHeaders });
      if (res.ok) setUsers(await res.json());
    } catch {}
  }, [token]);

  // ── Fetch conversation list ──
  const fetchConversations = useCallback(async () => {
    try {
      const res = await fetch(apiUrl('/api/messaging/conversations'), { headers: authHeaders });
      if (res.ok) {
        const data = await res.json();
        setConversations(data);
        // Update nav badge in parent
        if (onUnreadChange) {
          const total = data.reduce((sum, c) => sum + (c.unread_count || 0), 0);
          onUnreadChange(total);
        }
      }
    } catch {}
  }, [token]);

  // ── Fetch messages for selected conversation ──
  const fetchMessages = useCallback(async (partnerId, silent = false) => {
    if (!partnerId) return;
    if (!silent) setLoadingMessages(true);
    try {
      const res = await fetch(apiUrl(`/api/messaging/conversations/${partnerId}/messages`), { headers: authHeaders });
      if (res.ok) {
        setMessages(await res.json());
        // Mark as read
        fetch(apiUrl(`/api/messaging/conversations/${partnerId}/read`), {
          method: 'POST', headers: authHeaders
        }).catch(() => {});
      }
    } catch {}
    if (!silent) setLoadingMessages(false);
  }, [token]);

  // ── On mount: fetch users + conversations ──
  useEffect(() => {
    fetchUsers();
    fetchConversations();
  }, [fetchUsers, fetchConversations]);

  // ── Poll when conversation is open ──
  useEffect(() => {
    if (selectedUser) {
      fetchConversations();
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = setInterval(() => {
        fetchMessages(selectedUser.user_id, true);
        fetchConversations();
      }, POLL_INTERVAL);
    } else {
      if (pollRef.current) clearInterval(pollRef.current);
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [selectedUser, fetchMessages, fetchConversations]);

  // ── Auto-scroll to bottom on new messages ──
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // ── Focus input when conversation selected ──
  useEffect(() => {
    if (selectedUser) inputRef.current?.focus();
  }, [selectedUser]);

  const selectUser = async (u) => {
    setSelectedUser(u);
    setMessages([]);
    setInput('');
    // Optimistically clear unread for this chat in the nav badge
    if (onUnreadChange) {
      const openConvo = conversations.find(c => c.partner_id === u.user_id);
      if (openConvo?.unread_count > 0) {
        const newTotal = conversations.reduce(
          (sum, c) => sum + (c.partner_id === u.user_id ? 0 : (c.unread_count || 0)), 0
        );
        onUnreadChange(newTotal);
      }
    }
    await fetchMessages(u.user_id);
    // Refresh convos to get updated unread counts
    fetchConversations();
  };

  const sendMessage = async () => {
    if (!input.trim() || !selectedUser || sending) return;
    setSending(true);
    const content = input.trim();
    setInput('');
    try {
      const res = await fetch(apiUrl(`/api/messaging/conversations/${selectedUser.user_id}/messages`), {
        method: 'POST',
        headers: { ...authHeaders, 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
      });
      if (res.ok) {
        const msg = await res.json();
        setMessages(prev => [...prev, msg]);
        fetchConversations();
      }
    } catch {}
    setSending(false);
  };

  const handleKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  // ── Merge users list with conversations to show recent on top ──
  const filteredUsers = users.filter(u => {
    const t = search.toLowerCase();
    return (
      !t ||
      (u.full_name || '').toLowerCase().includes(t) ||
      (u.user_id || '').toLowerCase().includes(t) ||
      (u.department || '').toLowerCase().includes(t)
    );
  });

  // Group: people with existing convos first
  const convPartnerIds = new Set(conversations.map(c => c.partner_id));
  const withConvo = filteredUsers.filter(u => convPartnerIds.has(u.user_id));
  const withoutConvo = filteredUsers.filter(u => !convPartnerIds.has(u.user_id));

  const getConvoFor = (uid) => conversations.find(c => c.partner_id === uid);

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
    return name.split(' ').map(p => p[0]).join('').toUpperCase().slice(0, 2);
  };

  const avatarColors = ['#6366f1', '#8b5cf6', '#ec4899', '#14b8a6', '#f59e0b', '#10b981', '#3b82f6', '#ef4444'];
  const getAvatarColor = (uid = '') => avatarColors[uid.charCodeAt(0) % avatarColors.length];

  return (
    <div style={{
      display: 'flex',
      height: '100%',
      background: 'var(--color-bg, #0f0f1a)',
      fontFamily: "'Inter', 'Segoe UI', sans-serif",
      overflow: 'hidden',
    }}>

      {/* ── Left Panel: User / Conversation List ── */}
      <div style={{
        width: selectedUser ? '280px' : '100%',
        maxWidth: '340px',
        flexShrink: 0,
        display: 'flex',
        flexDirection: 'column',
        background: 'var(--color-surface, #1e1e2e)',
        borderRight: '1px solid var(--color-border-subtle, #252535)',
        transition: 'width 0.25s ease',
        overflow: 'hidden',
      }}>
        {/* Header */}
        <div style={{
          padding: '20px 16px 12px',
          borderBottom: '1px solid var(--color-border-subtle, #252535)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '14px' }}>
            <h2 style={{ margin: 0, fontSize: '17px', fontWeight: '700', color: 'var(--color-text, #e2e8f0)' }}>
              Messages
            </h2>
            {conversations.reduce((sum, c) => sum + (c.unread_count || 0), 0) > 0 && (
              <span style={{
                minWidth: '20px', height: '20px', borderRadius: '10px',
                background: 'linear-gradient(135deg, #6366f1, #8b5cf6)',
                color: '#fff', fontSize: '11px', fontWeight: '700',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                padding: '0 6px',
                boxShadow: '0 2px 8px rgba(99,102,241,0.4)',
              }}>
                {conversations.reduce((sum, c) => sum + (c.unread_count || 0), 0)}
              </span>
            )}
          </div>
          {/* Search */}
          <div style={{ position: 'relative' }}>
            <FontAwesomeIcon icon={faSearch} style={{
              position: 'absolute', left: '11px', top: '50%', transform: 'translateY(-50%)',
              color: 'var(--color-text-muted, #64748b)', fontSize: '12px',
            }} />
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search users..."
              style={{
                width: '100%',
                boxSizing: 'border-box',
                padding: '8px 12px 8px 32px',
                borderRadius: '10px',
                border: '1px solid var(--color-border, #2a2a3e)',
                background: 'var(--color-elevated, #252535)',
                color: 'var(--color-text, #e2e8f0)',
                fontSize: '13px',
                outline: 'none',
              }}
            />
          </div>
        </div>

        {/* User list */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '8px 0' }}>
          {/* Recent conversations */}
          {withConvo.length > 0 && (
            <>
              <div style={{ padding: '6px 16px 4px', fontSize: '10px', fontWeight: '700', color: 'var(--color-text-muted, #64748b)', textTransform: 'uppercase', letterSpacing: '0.8px' }}>
                Recent
              </div>
              {withConvo.map(u => {
                const convo = getConvoFor(u.user_id);
                const isActive = selectedUser?.user_id === u.user_id;
                return (
                  <UserRow
                    key={u.user_id}
                    u={u} convo={convo} isActive={isActive}
                    onSelect={() => selectUser(u)}
                    getInitials={getInitials}
                    getAvatarColor={getAvatarColor}
                    formatTime={formatTime}
                  />
                );
              })}
            </>
          )}

          {/* All other users */}
          {withoutConvo.length > 0 && (
            <>
              <div style={{ padding: '10px 16px 4px', fontSize: '10px', fontWeight: '700', color: 'var(--color-text-muted, #64748b)', textTransform: 'uppercase', letterSpacing: '0.8px' }}>
                {withConvo.length > 0 ? 'Other Users' : 'All Users'}
              </div>
              {withoutConvo.map(u => {
                const isActive = selectedUser?.user_id === u.user_id;
                return (
                  <UserRow
                    key={u.user_id}
                    u={u} convo={null} isActive={isActive}
                    onSelect={() => selectUser(u)}
                    getInitials={getInitials}
                    getAvatarColor={getAvatarColor}
                    formatTime={formatTime}
                  />
                );
              })}
            </>
          )}

          {filteredUsers.length === 0 && (
            <div style={{ padding: '40px 16px', textAlign: 'center', color: 'var(--color-text-muted, #64748b)', fontSize: '13px' }}>
              <FontAwesomeIcon icon={faComments} style={{ fontSize: '28px', opacity: 0.25, display: 'block', marginBottom: '12px' }} />
              No users found
            </div>
          )}
        </div>
      </div>

      {/* ── Right Panel: Chat Window ── */}
      {selectedUser ? (
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>
          {/* Chat header */}
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '12px',
            padding: '14px 20px',
            borderBottom: '1px solid var(--color-border-subtle, #252535)',
            background: 'var(--color-surface, #1e1e2e)',
            flexShrink: 0,
          }}>
            <button
              onClick={() => setSelectedUser(null)}
              style={{
                width: '32px', height: '32px', borderRadius: '8px',
                border: 'none', background: 'transparent',
                color: 'var(--color-text-muted, #64748b)',
                cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
                transition: 'background 0.15s',
              }}
              onMouseEnter={e => e.currentTarget.style.background = 'var(--color-hover, rgba(255,255,255,0.05))'}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
            >
              <FontAwesomeIcon icon={faChevronLeft} />
            </button>
            <div style={{
              width: '36px', height: '36px', borderRadius: '50%', flexShrink: 0,
              background: getAvatarColor(selectedUser.user_id),
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              color: '#fff', fontWeight: '700', fontSize: '13px',
            }}>
              {getInitials(selectedUser.full_name)}
            </div>
            <div>
              <div style={{ fontSize: '14px', fontWeight: '600', color: 'var(--color-text, #e2e8f0)' }}>
                {selectedUser.full_name}
              </div>
              <div style={{ fontSize: '11px', color: 'var(--color-text-muted, #64748b)' }}>
                {selectedUser.department} · {selectedUser.role}
              </div>
            </div>
          </div>

          {/* Messages area */}
          <div style={{
            flex: 1, overflowY: 'auto', padding: '20px 24px',
            display: 'flex', flexDirection: 'column', gap: '4px',
            background: 'var(--color-bg, #0f0f1a)',
          }}>
            {loadingMessages ? (
              <div style={{ textAlign: 'center', color: 'var(--color-text-muted, #64748b)', paddingTop: '60px' }}>
                <FontAwesomeIcon icon={faSpinner} spin style={{ fontSize: '22px', opacity: 0.4 }} />
              </div>
            ) : messages.length === 0 ? (
              <div style={{ textAlign: 'center', color: 'var(--color-text-muted, #64748b)', paddingTop: '60px', fontSize: '13px' }}>
                <FontAwesomeIcon icon={faComments} style={{ fontSize: '32px', opacity: 0.2, display: 'block', marginBottom: '12px' }} />
                No messages yet. Say hello! 👋
              </div>
            ) : (
              <MessageBubbles
                messages={messages}
                currentUserId={user.user_id}
                formatMsgTime={formatMsgTime}
                getInitials={getInitials}
                getAvatarColor={getAvatarColor}
                selectedUser={selectedUser}
              />
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Input bar */}
          <div style={{
            padding: '14px 20px',
            borderTop: '1px solid var(--color-border-subtle, #252535)',
            background: 'var(--color-surface, #1e1e2e)',
            display: 'flex',
            alignItems: 'flex-end',
            gap: '10px',
            flexShrink: 0,
          }}>
            <textarea
              ref={inputRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKey}
              placeholder={`Message ${selectedUser.full_name}...`}
              rows={1}
              style={{
                flex: 1,
                padding: '10px 14px',
                borderRadius: '12px',
                border: '1px solid var(--color-border, #2a2a3e)',
                background: 'var(--color-elevated, #252535)',
                color: 'var(--color-text, #e2e8f0)',
                fontSize: '14px',
                resize: 'none',
                outline: 'none',
                lineHeight: '1.5',
                maxHeight: '120px',
                overflowY: 'auto',
                transition: 'border-color 0.15s',
                fontFamily: 'inherit',
              }}
              onFocus={e => e.target.style.borderColor = '#6366f1'}
              onBlur={e => e.target.style.borderColor = 'var(--color-border, #2a2a3e)'}
              onInput={e => {
                e.target.style.height = 'auto';
                e.target.style.height = Math.min(e.target.scrollHeight, 120) + 'px';
              }}
            />
            <button
              onClick={sendMessage}
              disabled={!input.trim() || sending}
              style={{
                width: '42px', height: '42px', borderRadius: '12px',
                border: 'none', flexShrink: 0,
                background: input.trim() && !sending
                  ? 'linear-gradient(135deg, #6366f1, #8b5cf6)'
                  : 'var(--color-border, #2a2a3e)',
                color: input.trim() && !sending ? '#fff' : 'var(--color-text-muted, #64748b)',
                cursor: input.trim() && !sending ? 'pointer' : 'not-allowed',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: '15px',
                transition: 'all 0.15s ease',
                boxShadow: input.trim() && !sending ? '0 4px 14px rgba(99,102,241,0.4)' : 'none',
              }}
            >
              {sending
                ? <FontAwesomeIcon icon={faSpinner} spin style={{ fontSize: '14px' }} />
                : <FontAwesomeIcon icon={faPaperPlane} />
              }
            </button>
          </div>
        </div>
      ) : (
        /* Empty state when no conversation selected */
        <div style={{
          flex: 1, display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center',
          color: 'var(--color-text-muted, #64748b)',
          background: 'var(--color-bg, #0f0f1a)',
          gap: '16px',
        }}>
          <div style={{
            width: '72px', height: '72px', borderRadius: '20px',
            background: 'linear-gradient(135deg, rgba(99,102,241,0.15), rgba(139,92,246,0.15))',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            marginBottom: '4px',
          }}>
            <FontAwesomeIcon icon={faComments} style={{ fontSize: '30px', color: '#6366f1', opacity: 0.7 }} />
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: '16px', fontWeight: '600', color: 'var(--color-text, #e2e8f0)', marginBottom: '6px' }}>
              Your Messages
            </div>
            <div style={{ fontSize: '13px', maxWidth: '260px', lineHeight: '1.6' }}>
              Select a person from the list to start a conversation
            </div>
          </div>
        </div>
      )}

      <style>{`
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 2px; }
        .msg-bubble-enter { animation: msg-in 0.15s ease both; }
        @keyframes msg-in {
          from { opacity: 0; transform: translateY(6px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}

/* ── Sub-components ── */

function UserRow({ u, convo, isActive, onSelect, getInitials, getAvatarColor, formatTime }) {
  const [hovered, setHovered] = useState(false);
  return (
    <div
      onClick={onSelect}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: 'flex', alignItems: 'center', gap: '12px',
        padding: '10px 16px', cursor: 'pointer',
        background: isActive
          ? 'rgba(99,102,241,0.12)'
          : hovered ? 'var(--color-hover, rgba(255,255,255,0.04))' : 'transparent',
        borderLeft: isActive ? '3px solid #6366f1' : '3px solid transparent',
        transition: 'all 0.12s ease',
      }}
    >
      {/* Avatar */}
      <div style={{
        width: '40px', height: '40px', borderRadius: '50%', flexShrink: 0,
        background: getAvatarColor(u.user_id),
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: '#fff', fontWeight: '700', fontSize: '14px',
        boxShadow: isActive ? `0 0 0 2px #6366f1` : 'none',
        transition: 'box-shadow 0.12s',
      }}>
        {getInitials(u.full_name)}
      </div>

      {/* Info */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
          <span style={{
            fontSize: '13px', fontWeight: convo?.unread_count > 0 ? '700' : '500',
            color: 'var(--color-text, #e2e8f0)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>
            {u.full_name || u.user_id}
          </span>
          {convo?.last_timestamp && (
            <span style={{ fontSize: '10px', color: 'var(--color-text-muted, #64748b)', flexShrink: 0, marginLeft: '6px' }}>
              {formatTime(convo.last_timestamp)}
            </span>
          )}
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '2px' }}>
          <span style={{
            fontSize: '11.5px',
            color: convo?.unread_count > 0 ? 'var(--color-text, #e2e8f0)' : 'var(--color-text-muted, #64748b)',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1,
            fontWeight: convo?.unread_count > 0 ? '500' : '400',
          }}>
            {convo ? convo.last_message : u.department || u.role || 'Start a conversation'}
          </span>
          {convo?.unread_count > 0 && (
            <span style={{
              minWidth: '18px', height: '18px', borderRadius: '9px',
              background: '#6366f1', color: '#fff',
              fontSize: '10px', fontWeight: '700',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              padding: '0 4px', marginLeft: '6px', flexShrink: 0,
            }}>
              {convo.unread_count}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function MessageBubbles({ messages, currentUserId, formatMsgTime, getInitials, getAvatarColor, selectedUser }) {
  // Group consecutive messages by sender
  const groups = [];
  for (const msg of messages) {
    const isMine = msg.sender_id === currentUserId;
    if (groups.length === 0 || groups[groups.length - 1].isMine !== isMine) {
      groups.push({ isMine, msgs: [msg] });
    } else {
      groups[groups.length - 1].msgs.push(msg);
    }
  }

  return (
    <>
      {groups.map((group, gi) => (
        <div
          key={gi}
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: group.isMine ? 'flex-end' : 'flex-start',
            marginBottom: '10px',
          }}
        >
          {!group.isMine && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
              <div style={{
                width: '24px', height: '24px', borderRadius: '50%',
                background: getAvatarColor(selectedUser.user_id),
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                color: '#fff', fontSize: '9px', fontWeight: '700',
              }}>
                {getInitials(selectedUser.full_name)}
              </div>
              <span style={{ fontSize: '11px', color: 'var(--color-text-muted, #64748b)', fontWeight: '500' }}>
                {selectedUser.full_name}
              </span>
            </div>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '3px', alignItems: group.isMine ? 'flex-end' : 'flex-start', maxWidth: '70%' }}>
            {group.msgs.map((msg, mi) => (
              <div
                key={msg.id || mi}
                className="msg-bubble-enter"
                title={formatMsgTime(msg.timestamp)}
                style={{
                  padding: '9px 14px',
                  borderRadius: group.isMine
                    ? mi === 0 && group.msgs.length > 1 ? '18px 18px 4px 18px' : mi === group.msgs.length - 1 ? '4px 18px 18px 18px' : '4px 18px 4px 18px'
                    : mi === 0 && group.msgs.length > 1 ? '18px 18px 18px 4px' : mi === group.msgs.length - 1 ? '18px 4px 18px 18px' : '18px 4px 4px 18px',
                  background: group.isMine
                    ? 'linear-gradient(135deg, #6366f1, #8b5cf6)'
                    : 'var(--color-elevated, #252535)',
                  color: group.isMine ? '#fff' : 'var(--color-text, #e2e8f0)',
                  fontSize: '13.5px',
                  lineHeight: '1.5',
                  wordBreak: 'break-word',
                  boxShadow: group.isMine
                    ? '0 2px 8px rgba(99,102,241,0.25)'
                    : '0 1px 4px rgba(0,0,0,0.2)',
                }}
              >
                {msg.content}
              </div>
            ))}
            {/* timestamp on last msg */}
            <div style={{ fontSize: '10px', color: 'var(--color-text-muted, #64748b)', marginTop: '2px', opacity: 0.7 }}>
              {formatMsgTime(group.msgs[group.msgs.length - 1].timestamp)}
            </div>
          </div>
        </div>
      ))}
    </>
  );
}
