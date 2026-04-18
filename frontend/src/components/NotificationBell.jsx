import React, { useState, useEffect, useRef, useCallback } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faBell, faCheckCircle, faTimesCircle, faX, faTriangleExclamation, faArrowUpRightFromSquare } from '@fortawesome/free-solid-svg-icons';
import { apiUrl } from '../stores/configStore';

export default function NotificationBell({ token, isAdmin }) {
  const [notifications, setNotifications] = useState([]);
  const [open, setOpen] = useState(false);
  const [dismissing, setDismissing] = useState(null);
  const panelRef = useRef(null);
  const bellRef = useRef(null);

  const fetchNotifications = useCallback(async () => {
    if (!token) return;
    try {
      const endpoint = isAdmin
        ? '/api/admin/escalation-notifications'
        : '/api/users/my-notifications';
      const res = await fetch(apiUrl(endpoint), {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setNotifications(data);
      }
    } catch {
      // silently ignore network errors
    }
  }, [token, isAdmin]);

  // Poll every 30 seconds and on mount
  useEffect(() => {
    fetchNotifications();
    const interval = setInterval(fetchNotifications, 30000);
    return () => clearInterval(interval);
  }, [fetchNotifications]);

  // Close panel when clicking outside
  useEffect(() => {
    const handler = (e) => {
      if (
        panelRef.current && !panelRef.current.contains(e.target) &&
        bellRef.current && !bellRef.current.contains(e.target)
      ) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const dismiss = async (id, e) => {
    e.stopPropagation();
    setDismissing(id);
    try {
      const endpoint = isAdmin
        ? `/api/admin/escalation-notifications/${id}/dismiss`
        : `/api/users/my-notifications/${id}/dismiss`;
      await fetch(apiUrl(endpoint), {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      setNotifications(prev => prev.filter(n => n.id !== id));
    } catch {
      // ignore
    } finally {
      setDismissing(null);
    }
  };

  const dismissAll = async () => {
    const endpoint = isAdmin
      ? '/api/admin/escalation-notifications'
      : '/api/users/my-notifications';
    for (const n of notifications) {
      try {
        await fetch(apiUrl(`${endpoint}/${n.id}/dismiss`), {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
        });
      } catch {}
    }
    setNotifications([]);
  };

  const count = notifications.length;

  const formatTime = (iso) => {
    if (!iso) return '';
    const d = new Date(iso);
    return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  };

  // ── Accent colour per mode ──
  const accentColor = isAdmin ? '#f59e0b' : '#3b82f6'; // amber for admin, blue for user

  return (
    <div className="relative" style={{ display: 'inline-block' }}>
      {/* Bell Button */}
      <button
        ref={bellRef}
        id="notif-bell-btn"
        onClick={() => setOpen(o => !o)}
        title={isAdmin ? 'Escalation Alerts' : 'Notifications'}
        style={{
          position: 'relative',
          width: '36px',
          height: '36px',
          borderRadius: '10px',
          border: open ? `1.5px solid ${accentColor}` : '1.5px solid transparent',
          background: open ? `${accentColor}18` : 'transparent',
          color: count > 0 ? accentColor : 'var(--color-text-muted, #9ca3af)',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: '16px',
          transition: 'all 0.15s ease',
          flexShrink: 0,
        }}
        onMouseEnter={e => {
          e.currentTarget.style.background = `${accentColor}14`;
          e.currentTarget.style.color = accentColor;
        }}
        onMouseLeave={e => {
          if (!open) {
            e.currentTarget.style.background = 'transparent';
            e.currentTarget.style.color = count > 0 ? accentColor : 'var(--color-text-muted, #9ca3af)';
          }
        }}
      >
        <FontAwesomeIcon icon={faBell} style={{ animation: count > 0 ? 'bell-ring 1.5s ease 0s 2' : 'none' }} />
        {count > 0 && (
          <span style={{
            position: 'absolute',
            top: '3px',
            right: '3px',
            width: '16px',
            height: '16px',
            borderRadius: '50%',
            background: isAdmin ? '#f59e0b' : '#ef4444',
            color: '#fff',
            fontSize: '9px',
            fontWeight: '700',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            lineHeight: 1,
            boxShadow: '0 0 0 2px var(--color-surface, #1a1a2e)',
          }}>
            {count > 9 ? '9+' : count}
          </span>
        )}
      </button>

      {/* Dropdown Panel */}
      {open && (
        <div
          ref={panelRef}
          id="notif-panel"
          style={{
            position: 'absolute',
            bottom: 'calc(100% + 8px)',
            left: '50%',
            transform: 'translateX(-50%)',
            width: '330px',
            background: 'var(--color-surface, #1e1e2e)',
            border: '1px solid var(--color-border, #2a2a3e)',
            borderRadius: '14px',
            boxShadow: '0 16px 40px rgba(0,0,0,0.4), 0 0 0 1px rgba(255,255,255,0.04)',
            zIndex: 1000,
            overflow: 'hidden',
            animation: 'notif-panel-in 0.18s cubic-bezier(0.34,1.56,0.64,1)',
          }}
        >
          {/* Header */}
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '12px 16px',
            borderBottom: '1px solid var(--color-border-subtle, #252535)',
            background: 'var(--color-elevated, #252535)',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <FontAwesomeIcon
                icon={isAdmin ? faTriangleExclamation : faBell}
                style={{ color: accentColor, fontSize: '13px' }}
              />
              <span style={{ fontSize: '13px', fontWeight: '600', color: 'var(--color-text, #e2e8f0)' }}>
                {isAdmin ? 'Escalation Alerts' : 'Notifications'}
              </span>
              {count > 0 && (
                <span style={{
                  fontSize: '10px',
                  fontWeight: '700',
                  background: accentColor,
                  color: '#fff',
                  padding: '1px 6px',
                  borderRadius: '9999px',
                }}>
                  {count}
                </span>
              )}
            </div>
            {count > 0 && (
              <button
                onClick={dismissAll}
                title="Dismiss all"
                style={{
                  fontSize: '10px',
                  color: 'var(--color-text-muted, #64748b)',
                  background: 'none',
                  border: 'none',
                  cursor: 'pointer',
                  padding: '2px 6px',
                  borderRadius: '6px',
                  transition: 'background 0.1s',
                }}
                onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,255,255,0.06)'}
                onMouseLeave={e => e.currentTarget.style.background = 'none'}
              >
                Clear all
              </button>
            )}
          </div>

          {/* Notification List */}
          <div style={{ maxHeight: '340px', overflowY: 'auto' }}>
            {count === 0 ? (
              <div style={{
                padding: '32px 16px',
                textAlign: 'center',
                color: 'var(--color-text-muted, #64748b)',
                fontSize: '13px',
              }}>
                <FontAwesomeIcon icon={faBell} style={{ fontSize: '24px', opacity: 0.3, display: 'block', marginBottom: '10px' }} />
                {isAdmin ? 'No pending escalation requests' : 'No new notifications'}
              </div>
            ) : isAdmin ? (
              // ── Admin: escalation request notifications ──
              notifications.map((n, i) => (
                <div
                  key={n.id}
                  style={{
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: '10px',
                    padding: '12px 16px',
                    borderBottom: i < notifications.length - 1 ? '1px solid var(--color-border-subtle, #252535)' : 'none',
                    background: 'rgba(245,158,11,0.04)',
                    transition: 'background 0.15s',
                    animation: `notif-slide-in 0.2s ease ${i * 0.05}s both`,
                  }}
                >
                  {/* Icon */}
                  <div style={{
                    width: '32px',
                    height: '32px',
                    borderRadius: '50%',
                    background: 'rgba(245,158,11,0.15)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    flexShrink: 0,
                    marginTop: '2px',
                  }}>
                    <FontAwesomeIcon icon={faTriangleExclamation} style={{ color: '#f59e0b', fontSize: '14px' }} />
                  </div>

                  {/* Content */}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: '12.5px', fontWeight: '600', color: 'var(--color-text, #e2e8f0)', lineHeight: 1.4, display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
                      <span style={{
                        background: 'rgba(245,158,11,0.15)',
                        color: '#f59e0b',
                        padding: '1px 6px',
                        borderRadius: '4px',
                        fontSize: '10px',
                        fontWeight: '700',
                        textTransform: 'uppercase',
                        letterSpacing: '0.5px',
                      }}>
                        Escalation
                      </span>
                      <span style={{ fontFamily: 'monospace', fontSize: '12px' }}>{n.resource_type}</span>
                    </div>
                    <div style={{ fontSize: '11px', color: 'var(--color-text-muted, #64748b)', marginTop: '3px' }}>
                      From user <span style={{ fontFamily: 'monospace', color: 'var(--color-text, #e2e8f0)' }}>{n.user_id}</span> is requesting access
                    </div>
                    {n.timestamp && (
                      <div style={{ fontSize: '10px', color: 'var(--color-text-muted, #64748b)', marginTop: '4px', opacity: 0.7 }}>
                        {formatTime(n.timestamp)}
                      </div>
                    )}
                  </div>

                  {/* Dismiss X */}
                  <button
                    onClick={(e) => dismiss(n.id, e)}
                    disabled={dismissing === n.id}
                    title="Dismiss"
                    style={{
                      width: '22px',
                      height: '22px',
                      borderRadius: '6px',
                      border: 'none',
                      background: 'transparent',
                      color: 'var(--color-text-muted, #64748b)',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: '11px',
                      flexShrink: 0,
                      transition: 'background 0.1s, color 0.1s',
                      opacity: dismissing === n.id ? 0.4 : 1,
                    }}
                    onMouseEnter={e => {
                      e.currentTarget.style.background = 'rgba(245,158,11,0.12)';
                      e.currentTarget.style.color = '#f59e0b';
                    }}
                    onMouseLeave={e => {
                      e.currentTarget.style.background = 'transparent';
                      e.currentTarget.style.color = 'var(--color-text-muted, #64748b)';
                    }}
                  >
                    <FontAwesomeIcon icon={faX} />
                  </button>
                </div>
              ))
            ) : (
              // ── User: access request status notifications ──
              notifications.map((n, i) => {
                const isApproved = n.status === 'approved';
                return (
                  <div
                    key={n.id}
                    style={{
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: '10px',
                      padding: '12px 16px',
                      borderBottom: i < notifications.length - 1 ? '1px solid var(--color-border-subtle, #252535)' : 'none',
                      background: isApproved
                        ? 'rgba(34,197,94,0.04)'
                        : 'rgba(239,68,68,0.04)',
                      transition: 'background 0.15s',
                      animation: `notif-slide-in 0.2s ease ${i * 0.05}s both`,
                    }}
                  >
                    {/* Status Icon */}
                    <div style={{
                      width: '32px',
                      height: '32px',
                      borderRadius: '50%',
                      background: isApproved ? 'rgba(34,197,94,0.15)' : 'rgba(239,68,68,0.15)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      flexShrink: 0,
                      marginTop: '2px',
                    }}>
                      <FontAwesomeIcon
                        icon={isApproved ? faCheckCircle : faTimesCircle}
                        style={{
                          color: isApproved ? '#22c55e' : '#ef4444',
                          fontSize: '14px',
                        }}
                      />
                    </div>

                    {/* Content */}
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: '12.5px', fontWeight: '600', color: 'var(--color-text, #e2e8f0)', lineHeight: 1.4 }}>
                        <span style={{
                          background: isApproved ? 'rgba(34,197,94,0.15)' : 'rgba(239,68,68,0.15)',
                          color: isApproved ? '#22c55e' : '#ef4444',
                          padding: '1px 6px',
                          borderRadius: '4px',
                          fontSize: '10px',
                          fontWeight: '700',
                          textTransform: 'uppercase',
                          letterSpacing: '0.5px',
                          marginRight: '6px',
                        }}>
                          {isApproved ? 'Approved' : 'Denied'}
                        </span>
                        <span style={{ fontFamily: 'monospace', fontSize: '12px', color: 'var(--color-text, #e2e8f0)' }}>
                          {n.resource_type}
                        </span>
                      </div>
                      <div style={{ fontSize: '11px', color: 'var(--color-text-muted, #64748b)', marginTop: '3px' }}>
                        {isApproved
                          ? `Your request for ${n.resource_type} has been approved ✓`
                          : `Your request for ${n.resource_type} has been denied ✗`}
                      </div>
                      {n.timestamp && (
                        <div style={{ fontSize: '10px', color: 'var(--color-text-muted, #64748b)', marginTop: '4px', opacity: 0.7 }}>
                          {formatTime(n.timestamp)}
                        </div>
                      )}
                    </div>

                    {/* Dismiss X */}
                    <button
                      onClick={(e) => dismiss(n.id, e)}
                      disabled={dismissing === n.id}
                      title="Dismiss"
                      style={{
                        width: '22px',
                        height: '22px',
                        borderRadius: '6px',
                        border: 'none',
                        background: 'transparent',
                        color: 'var(--color-text-muted, #64748b)',
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        fontSize: '11px',
                        flexShrink: 0,
                        transition: 'background 0.1s, color 0.1s',
                        opacity: dismissing === n.id ? 0.4 : 1,
                      }}
                      onMouseEnter={e => {
                        e.currentTarget.style.background = 'rgba(239,68,68,0.12)';
                        e.currentTarget.style.color = '#ef4444';
                      }}
                      onMouseLeave={e => {
                        e.currentTarget.style.background = 'transparent';
                        e.currentTarget.style.color = 'var(--color-text-muted, #64748b)';
                      }}
                    >
                      <FontAwesomeIcon icon={faX} />
                    </button>
                  </div>
                );
              })
            )}
          </div>

          {/* Footer tip */}
          {count > 0 && (
            <div style={{
              padding: '8px 16px',
              borderTop: '1px solid var(--color-border-subtle, #252535)',
              fontSize: '10px',
              color: 'var(--color-text-muted, #64748b)',
              textAlign: 'center',
            }}>
              {isAdmin
                ? 'Dismiss to clear from bell • Review in Policy Admin tab'
                : 'Click ✕ to dismiss individual notifications'}
            </div>
          )}
        </div>
      )}

      <style>{`
        @keyframes bell-ring {
          0%,100% { transform: rotate(0deg); }
          15% { transform: rotate(12deg); }
          30% { transform: rotate(-10deg); }
          45% { transform: rotate(8deg); }
          60% { transform: rotate(-6deg); }
          75% { transform: rotate(4deg); }
          90% { transform: rotate(-2deg); }
        }
        @keyframes notif-panel-in {
          from { opacity: 0; transform: translateX(-50%) scale(0.95) translateY(6px); }
          to   { opacity: 1; transform: translateX(-50%) scale(1) translateY(0); }
        }
        @keyframes notif-slide-in {
          from { opacity: 0; transform: translateX(-8px); }
          to   { opacity: 1; transform: translateX(0); }
        }
      `}</style>
    </div>
  );
}
