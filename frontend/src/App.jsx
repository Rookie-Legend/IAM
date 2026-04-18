import React, { useState, useEffect, useCallback } from 'react';
import ChatInterface from './pages/ChatInterface';
import Joiner from './pages/Joiner';
import AdminDashboard from './pages/AdminDashboard';
import AdminJoiner from './pages/AdminJoiner';
import AuditDashboard from './pages/AuditDashboard';
import VPNCenter from './pages/VPNCenter';
import LoginPage from './pages/LoginPage';
import Profile from './pages/Profile';
import MessagingPage from './pages/MessagingPage';
import NotificationBell from './components/NotificationBell';
import { useTheme } from './contexts/ThemeContext';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faUser, faComment, faServer, faShieldHalved, faChartBar,
  faRightFromBracket, faSun, faMoon, faUserPlus, faComments,
  faChevronLeft, faChevronRight,
} from '@fortawesome/free-solid-svg-icons';
import { apiUrl } from './stores/configStore';
import './App.css';

function App() {
  const { theme, toggleTheme } = useTheme();
  const [user, setUser] = useState(() => {
    const saved = localStorage.getItem('iam_user');
    return saved ? JSON.parse(saved) : null;
  });
  const [token, setToken] = useState(() => localStorage.getItem('iam_token'));
  const [vpnMark, setVpnMark] = useState(null);
  const [activeTab, setActiveTab] = useState(() => localStorage.getItem('iam_active_tab') || 'chat');
  const [showJoiner, setShowJoiner] = useState(false);
  const [chatMessages, setChatMessages] = useState([]);
  const [accessState, setAccessState] = useState({ vpn_access: [] });

  // ── Collapsible nav ──
  const [navCollapsed, setNavCollapsed] = useState(() =>
    localStorage.getItem('iam_nav_collapsed') === 'true'
  );

  // ── Total unread messages badge (for Messages nav item) ──
  const [totalUnread, setTotalUnread] = useState(0);

  function handleLogout() {
    setUser(null);
    setToken(null);
    setVpnMark(null);
    setShowJoiner(false);
    localStorage.removeItem('iam_user');
    localStorage.removeItem('iam_token');
    localStorage.removeItem('iam_active_tab');
    setChatMessages([]);
    setTotalUnread(0);
  }

  const fetchAccessState = async () => {
    if (!user || !token) return;
    const userId = user.user_id;
    try {
      const res = await fetch(apiUrl(`/api/orchestrator/access/${userId}`), {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (res.status === 401) {
        handleLogout();
        return;
      }
      if (res.ok) {
        const data = await res.json();
        setAccessState(data);
      }
    } catch (err) {
      console.error("Failed to fetch access state", err);
    }
  };

  // ── Fetch total unread messages count (non-admin only) ──
  const fetchUnreadCount = useCallback(async () => {
    if (!token || !user) return;
    const ADMIN_ROLES = ['Security Admin', 'System Administrator', 'HR Manager', 'admin'];
    if (ADMIN_ROLES.includes(user.role)) return;
    try {
      const res = await fetch(apiUrl('/api/messaging/conversations'), {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const convos = await res.json();
        const total = convos.reduce((sum, c) => sum + (c.unread_count || 0), 0);
        setTotalUnread(total);
      }
    } catch {}
  }, [token, user]);

  useEffect(() => {
    if (activeTab) {
      localStorage.setItem('iam_active_tab', activeTab);
    }
    // Clear unread when Messages tab is opened
    if (activeTab === 'messages') {
      setTotalUnread(0);
    }
  }, [activeTab]);

  // Persist nav collapse state
  useEffect(() => {
    localStorage.setItem('iam_nav_collapsed', navCollapsed ? 'true' : 'false');
  }, [navCollapsed]);

  useEffect(() => {
    if (user) {
      fetchAccessState();
      fetchUnreadCount();

      const isAdmin = user.role.toLowerCase() === 'admin' || user.role === 'Security Admin' || user.department === 'HR';
      const welcomeText = isAdmin
        ? `🔐 Hello **${user.full_name}**! I'm your **IAM Security Assistant**.\n\nAs an Administrator, I can help you with:\n- ⚙️ **Policy Management**: Help you draft or refine access rules\n- 📊 **Security Auditing**: Analyze recent activities and anomalies\n- 🔍 **Policy Simulation**: Test "What-if" access scenarios\n\nHow can I assist with system oversight today?`
        : `👋 Hello **${user.full_name}**! I'm your **IAM Assistant**.\n\nI can help you:\n- 🔐 **Request VPN or resource access**\n- 📊 **Check your current access**\n- 🔍 **Explain any IAM decisions**\n- ✅ **Enter your MFA OTP**\n\nTry asking: *"What VPN do I have access to?"*`;

      setChatMessages([{
        role: 'bot',
        text: welcomeText
      }]);
    }
  }, [user]);

  // Poll unread count every 15 seconds (only when not on messages tab)
  useEffect(() => {
    if (!user || !token) return;
    const interval = setInterval(() => {
      if (activeTab !== 'messages') fetchUnreadCount();
    }, 15000);
    return () => clearInterval(interval);
  }, [fetchUnreadCount, activeTab, user, token]);

  const handleLogin = (userData, userToken, isJoinerRequest = false) => {
    if (isJoinerRequest) {
      setShowJoiner(true);
      return;
    }
    setUser(userData);
    setToken(userToken);
    localStorage.setItem('iam_user', JSON.stringify(userData));
    localStorage.setItem('iam_token', userToken);
    setShowJoiner(false);
    setActiveTab('chat');
  };

  if (showJoiner) {
    return <Joiner onBack={() => setShowJoiner(false)} />;
  }

  if (!user) {
    return <LoginPage onLogin={handleLogin} />;
  }

  // Match backend's admin_roles list exactly
  const ADMIN_ROLES = ['Security Admin', 'System Administrator', 'HR Manager', 'admin'];
  const isAdmin = ADMIN_ROLES.includes(user.role);

  const navItems = [
    { id: 'profile', icon: faUser, label: 'My Access' },
    { id: 'chat', icon: faComment, label: 'AI Assistant' },
    { id: 'lab', icon: faServer, label: 'VPN Center' },
  ];

  if (!isAdmin) {
    navItems.push({ id: 'messages', icon: faComments, label: 'Messages', badge: totalUnread > 0 ? totalUnread : null });
  }

  if (isAdmin) {
    navItems.push(
      { id: 'admin', icon: faShieldHalved, label: 'Policy Admin' },
      { id: 'admin_joiner', icon: faUserPlus, label: 'Onboard Joiner' },
    );
  }

  if (isAdmin && user.department !== 'HR') {
    navItems.push({ id: 'audit', icon: faChartBar, label: 'Audit Logs' });
  }

  const NAV_W_FULL = '240px';
  const NAV_W_COLLAPSED = '64px';

  return (
    <div className="flex h-screen">
      <aside
        style={{
          width: navCollapsed ? NAV_W_COLLAPSED : NAV_W_FULL,
          transition: 'width 0.22s cubic-bezier(0.4,0,0.2,1)',
          flexShrink: 0,
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
          background: 'var(--color-surface)',
          borderRight: '1px solid var(--color-border-subtle)',
          position: 'relative',
        }}
      >
        {/* ── Header ── */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: navCollapsed ? 'center' : 'space-between',
          padding: navCollapsed ? '20px 0' : '18px 16px 18px 20px',
          borderBottom: '1px solid var(--color-border-subtle)',
          minHeight: '65px',
          transition: 'padding 0.22s ease',
          overflow: 'hidden',
        }}>
          {!navCollapsed && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', minWidth: 0 }}>
              <img src="/logo.png" alt="CorpOD" style={{ width: '32px', height: '32px', objectFit: 'contain', flexShrink: 0 }} />
              <div style={{ fontSize: '14px', fontWeight: '600', lineHeight: '1.2', whiteSpace: 'nowrap' }}>
                CorpOD
                <small style={{ display: 'block', fontSize: '10px', fontWeight: '500', textTransform: 'uppercase', letterSpacing: '0.08em', marginTop: '1px', opacity: 0.6 }}>IAM</small>
              </div>
            </div>
          )}
          {navCollapsed && (
            <img src="/logo.png" alt="CorpOD" style={{ width: '28px', height: '28px', objectFit: 'contain' }} />
          )}
          {!navCollapsed && (
            <button
              onClick={toggleTheme}
              title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
              className="p-2 rounded-lg text-text-muted hover:bg-hover hover:text-text transition-all duration-150"
            >
              <FontAwesomeIcon icon={theme === 'dark' ? faSun : faMoon} />
            </button>
          )}
        </div>

        {/* ── Nav items ── */}
        <nav style={{
          flex: 1,
          padding: navCollapsed ? '12px 0' : '12px 8px',
          display: 'flex',
          flexDirection: 'column',
          gap: '2px',
          transition: 'padding 0.22s ease',
        }}>
          {navItems.map(item => {
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => setActiveTab(item.id)}
                title={navCollapsed ? item.label : undefined}
                style={{
                  position: 'relative',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: navCollapsed ? 'center' : 'flex-start',
                  gap: '10px',
                  padding: navCollapsed ? '10px 0' : '9px 12px',
                  borderRadius: navCollapsed ? '0' : '10px',
                  border: isActive && !navCollapsed ? '1px solid rgba(59,130,246,0.2)' : '1px solid transparent',
                  background: isActive
                    ? 'var(--color-accent-blue-muted, rgba(59,130,246,0.1))'
                    : 'transparent',
                  color: isActive ? 'var(--color-text, #e2e8f0)' : 'var(--color-text-secondary, #94a3b8)',
                  cursor: 'pointer',
                  fontSize: '13.5px',
                  fontWeight: isActive ? '600' : '500',
                  textAlign: 'left',
                  width: '100%',
                  transition: 'all 0.15s ease',
                  overflow: 'hidden',
                  whiteSpace: 'nowrap',
                }}
                onMouseEnter={e => {
                  if (!isActive) {
                    e.currentTarget.style.background = 'var(--color-hover, rgba(255,255,255,0.05))';
                    e.currentTarget.style.color = 'var(--color-text, #e2e8f0)';
                  }
                }}
                onMouseLeave={e => {
                  if (!isActive) {
                    e.currentTarget.style.background = 'transparent';
                    e.currentTarget.style.color = 'var(--color-text-secondary, #94a3b8)';
                  }
                }}
              >
                {/* Icon */}
                <span style={{
                  width: '20px',
                  textAlign: 'center',
                  flexShrink: 0,
                  fontSize: '15px',
                  position: 'relative',
                }}>
                  <FontAwesomeIcon icon={item.icon} />
                  {/* Badge on icon when collapsed */}
                  {navCollapsed && item.badge > 0 && (
                    <span style={{
                      position: 'absolute', top: '-5px', right: '-6px',
                      minWidth: '15px', height: '15px', borderRadius: '8px',
                      background: '#6366f1', color: '#fff',
                      fontSize: '9px', fontWeight: '700',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      padding: '0 3px', lineHeight: 1,
                      boxShadow: '0 0 0 2px var(--color-surface)',
                    }}>
                      {item.badge > 99 ? '99+' : item.badge}
                    </span>
                  )}
                </span>

                {/* Label + badge (expanded) */}
                {!navCollapsed && (
                  <>
                    <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis' }}>{item.label}</span>
                    {item.badge > 0 && (
                      <span style={{
                        minWidth: '18px', height: '18px', borderRadius: '9px',
                        background: '#6366f1', color: '#fff',
                        fontSize: '10px', fontWeight: '700',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        padding: '0 5px', lineHeight: 1, flexShrink: 0,
                        animation: 'badge-pulse 2s ease infinite',
                      }}>
                        {item.badge > 99 ? '99+' : item.badge}
                      </span>
                    )}
                  </>
                )}
              </button>
            );
          })}
        </nav>

        {/* ── Footer: user info + controls ── */}
        <div style={{
          padding: navCollapsed ? '12px 0' : '12px 12px',
          borderTop: '1px solid var(--color-border-subtle)',
          display: 'flex',
          flexDirection: 'column',
          gap: '8px',
          transition: 'padding 0.22s ease',
        }}>
          {/* Theme toggle (collapsed mode) */}
          {navCollapsed && (
            <button
              onClick={toggleTheme}
              title={theme === 'dark' ? 'Light mode' : 'Dark mode'}
              style={{
                width: '100%', padding: '8px 0', border: 'none', background: 'transparent',
                color: 'var(--color-text-muted)', cursor: 'pointer',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: '14px', borderRadius: '6px', transition: 'background 0.15s',
              }}
              onMouseEnter={e => e.currentTarget.style.background = 'var(--color-hover)'}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
            >
              <FontAwesomeIcon icon={theme === 'dark' ? faSun : faMoon} />
            </button>
          )}

          {/* User row */}
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: navCollapsed ? 'center' : 'space-between',
            gap: '8px',
            minWidth: 0,
          }}>
            {/* Avatar */}
            <div title={navCollapsed ? `${user.full_name || user.username} · ${user.role}` : undefined} style={{
              width: '34px', height: '34px', borderRadius: '50%', flexShrink: 0,
              background: 'linear-gradient(135deg, #3b82f6, #6366f1)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              color: '#fff', fontSize: '13px', fontWeight: '700',
            }}>
              {(user.full_name || user.username)[0].toUpperCase()}
            </div>

            {!navCollapsed && (
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: '12.5px', fontWeight: '600', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {user.full_name || user.username}
                </div>
                <div style={{ fontSize: '10.5px', color: 'var(--color-text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {user.role}
                </div>
              </div>
            )}

            {!navCollapsed && (
              <div style={{ display: 'flex', alignItems: 'center', gap: '2px', flexShrink: 0 }}>
                <NotificationBell token={token} isAdmin={isAdmin} />
                <button
                  onClick={handleLogout}
                  title="Sign Out"
                  className="p-2 rounded-md text-text-muted hover:bg-error/10 hover:text-error transition-all duration-150"
                >
                  <FontAwesomeIcon icon={faRightFromBracket} />
                </button>
              </div>
            )}
          </div>

          {/* Notification + logout stacked when collapsed */}
          {navCollapsed && (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '4px' }}>
              <NotificationBell token={token} isAdmin={isAdmin} />
              <button
                onClick={handleLogout}
                title="Sign Out"
                style={{
                  width: '36px', height: '36px', border: 'none', borderRadius: '8px',
                  background: 'transparent', cursor: 'pointer',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: '14px', color: 'var(--color-text-muted)',
                  transition: 'all 0.15s',
                }}
                onMouseEnter={e => { e.currentTarget.style.background = 'rgba(239,68,68,0.1)'; e.currentTarget.style.color = '#ef4444'; }}
                onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--color-text-muted)'; }}
              >
                <FontAwesomeIcon icon={faRightFromBracket} />
              </button>
            </div>
          )}
        </div>

        {/* ── Collapse toggle button ── */}
        <button
          onClick={() => setNavCollapsed(c => !c)}
          title={navCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          style={{
            position: 'absolute',
            top: '50%',
            right: '-12px',
            transform: 'translateY(-50%)',
            width: '24px',
            height: '24px',
            borderRadius: '50%',
            border: '1px solid var(--color-border, #2a2a3e)',
            background: 'var(--color-surface)',
            color: 'var(--color-text-muted)',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: '10px',
            zIndex: 10,
            boxShadow: '0 2px 8px rgba(0,0,0,0.25)',
            transition: 'all 0.15s ease',
          }}
          onMouseEnter={e => {
            e.currentTarget.style.background = '#6366f1';
            e.currentTarget.style.color = '#fff';
            e.currentTarget.style.borderColor = '#6366f1';
          }}
          onMouseLeave={e => {
            e.currentTarget.style.background = 'var(--color-surface)';
            e.currentTarget.style.color = 'var(--color-text-muted)';
            e.currentTarget.style.borderColor = 'var(--color-border, #2a2a3e)';
          }}
        >
          <FontAwesomeIcon icon={navCollapsed ? faChevronRight : faChevronLeft} />
        </button>
      </aside>

      <main className="flex-1 overflow-hidden relative">
        {activeTab === 'profile' && <Profile user={user} token={token} accessState={accessState} />}
        {activeTab === 'chat' && (
          <ChatInterface
            user={user}
            token={token}
            messages={chatMessages}
            setMessages={setChatMessages}
            accessState={accessState}
            refreshAccess={fetchAccessState}
          />
        )}
        {activeTab === 'lab' && <VPNCenter user={user} token={token} setVpnMark={setVpnMark} vpnMark={vpnMark} />}
        {activeTab === 'messages' && (
          <MessagingPage
            user={user}
            token={token}
            onUnreadChange={setTotalUnread}
          />
        )}
        {activeTab === 'admin' && <AdminDashboard token={token} />}
        {activeTab === 'admin_joiner' && <AdminJoiner token={token} />}
        {activeTab === 'audit' && <AuditDashboard token={token} />}
      </main>

      <style>{`
        @keyframes badge-pulse {
          0%, 100% { box-shadow: 0 0 0 0 rgba(99,102,241,0.4); }
          50% { box-shadow: 0 0 0 4px rgba(99,102,241,0); }
        }
      `}</style>
    </div>
  );
}

export default App;
