import React, { useState, useEffect } from 'react';
import ChatInterface from './pages/ChatInterface';
import Joiner from './pages/Joiner';
import AdminDashboard from './pages/AdminDashboard';
import AdminJoiner from './pages/AdminJoiner';
import AuditDashboard from './pages/AuditDashboard';
import VPNCenter from './pages/VPNCenter';
import LoginPage from './pages/LoginPage';
import Profile from './pages/Profile';
import { useTheme } from './contexts/ThemeContext';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faUser, faComment, faServer, faShieldHalved, faChartBar, faRightFromBracket, faSun, faMoon, faUserPlus } from '@fortawesome/free-solid-svg-icons';
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

  useEffect(() => {
    if (activeTab) {
      localStorage.setItem('iam_active_tab', activeTab);
    }
  }, [activeTab]);

  useEffect(() => {
    if (user) {
      fetchAccessState();

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

  const handleLogout = () => {
    setUser(null);
    setToken(null);
    setVpnMark(null);
    setShowJoiner(false);
    localStorage.removeItem('iam_user');
    localStorage.removeItem('iam_token');
    localStorage.removeItem('iam_active_tab');
    setChatMessages([]);
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

  if (isAdmin) {
    navItems.push(
      { id: 'admin', icon: faShieldHalved, label: 'Policy Admin' },
      { id: 'admin_joiner', icon: faUserPlus, label: 'Onboard Joiner' },
    );
  }

  if (isAdmin && user.department !== 'HR') {
    navItems.push({ id: 'audit', icon: faChartBar, label: 'Audit Logs' });
  }

  return (
    <div className="flex h-screen">
      <aside
        className="w-60 bg-surface border-r border-border-subtle flex flex-col shrink-0"
      >
        <div className="flex items-center justify-between px-5 py-6 border-b border-border-subtle">
          <div className="flex items-center gap-3">
            <img src="/logo.png" alt="CorpOD" className="w-8 h-8 object-contain" />
            <div className="text-sm font-semibold leading-tight">
              CorpOD
              <small className="block text-[11px] font-medium text-text-muted uppercase tracking-wider mt-0.5">IAM</small>
            </div>
          </div>
          <button
            onClick={toggleTheme}
            className="p-2 rounded-lg text-text-muted hover:bg-hover hover:text-text transition-all duration-150"
            title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          >
            {theme === 'dark' ? <FontAwesomeIcon icon={faSun} /> : <FontAwesomeIcon icon={faMoon} />}
          </button>
        </div>

        <nav className="flex-1 px-3 py-4 flex flex-col gap-1">
          {navItems.map(item => (
            <button
              key={item.id}
              onClick={() => setActiveTab(item.id)}
              className={`flex items-center gap-3 px-3.5 py-2.5 rounded-lg text-sm font-medium transition-all duration-150 text-left
                ${activeTab === item.id
                  ? 'bg-accent-blue-muted text-text border border-accent-blue/20'
                  : 'text-text-secondary hover:bg-hover hover:text-text'}`}
            >
              <FontAwesomeIcon icon={item.icon} className="w-5 text-center" />
              <span>{item.label}</span>
            </button>
          ))}
        </nav>

        <div className="px-4 py-4 border-t border-border-subtle">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="w-9 h-9 rounded-full bg-gradient-to-br from-accent-blue to-indigo-500 flex items-center justify-center text-white text-sm font-semibold">
                {(user.full_name || user.username)[0].toUpperCase()}
              </div>
              <div>
                <div className="text-[13px] font-semibold text-text">{user.full_name || user.username}</div>
                <div className="text-[11px] text-text-muted">{user.role}</div>
              </div>
            </div>
            <button
              onClick={handleLogout}
              title="Sign Out"
              className="p-2 rounded-md text-text-muted hover:bg-error/10 hover:text-error transition-all duration-150"
            >
              <FontAwesomeIcon icon={faRightFromBracket} />
            </button>
          </div>
        </div>
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
        {activeTab === 'admin' && <AdminDashboard token={token} />}
        {activeTab === 'admin_joiner' && <AdminJoiner token={token} />}
        {activeTab === 'audit' && <AuditDashboard token={token} />}
      </main>
    </div>
  );
}

export default App;
