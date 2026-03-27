import React, { useState, useEffect, useRef } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { 
  faKey, 
  faPlus, 
  faBuilding, 
  faCircleQuestion, 
  faClipboardList,
  faChartLine,
  faShieldHalved,
  faFlask,
  faGear,
  faPaperPlane,
  faShield
} from '@fortawesome/free-solid-svg-icons';

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000';

function renderMarkdown(text) {
  if (!text) return '';
  return (text || '')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code style="background:rgba(255,255,255,0.1);padding:1px 5px;border-radius:4px;font-size:12px">$1</code>')
    .replace(/\n/g, '<br/>');
}

export default function ChatInterface({ user, token, messages, setMessages, accessState, refreshAccess }) {
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const isAdmin = user.role.toLowerCase() === 'admin' || user.role === 'Security Admin';
  const isHR = user.role.toLowerCase() === 'hr manager' || user.role.toLowerCase() === 'hr';

  const USER_ACTIONS = [
    { label: 'Help', icon: faCircleQuestion, text: 'help' },
    { label: 'My VPN Access', icon: faKey, text: 'What VPN access do I currently have?' },
    { label: 'Request Engineering VPN', icon: faPlus, text: 'I want access to engineering_vpn' },
    { label: 'Request Finance VPN', icon: faBuilding, text: 'I want access to finance_vpn' },
  ];

  const ADMIN_ACTIONS = [
    { label: 'Help', icon: faCircleQuestion, text: 'help' },
    { label: 'Join Employee', icon: faPlus, text: 'Onboard a new employee' },
    { label: 'Move Employee', icon: faGear, text: 'Transfer an employee to a new department' },
    { label: 'Offboard', icon: faClipboardList, text: 'Offboard an employee' },
    { label: 'Disable User', icon: faShieldHalved, text: 'Disable a user account' },
    { label: 'Reinstate User', icon: faShieldHalved, text: 'Reinstate a disabled user' },
    { label: 'List Users', icon: faChartLine, text: 'Show all users' },
    { label: 'List Policies', icon: faClipboardList, text: 'Show all policies' },
    { label: 'Create Policy', icon: faPlus, text: 'Create a new policy' },
    { label: 'Delete Policy', icon: faClipboardList, text: 'Delete a policy' },
    { label: 'Edit Policy', icon: faGear, text: 'Update an existing policy' },
    { label: 'Suspicious Users', icon: faShieldHalved, text: 'Show suspicious users in the last 24 hours' },
  ];

  const HR_ACTIONS = [
    { label: 'Help', icon: faCircleQuestion, text: 'help' },
    { label: 'Join Employee', icon: faPlus, text: 'Onboard a new employee' },
    { label: 'Move Employee', icon: faGear, text: 'Transfer an employee to a new department' },
    { label: 'Offboard', icon: faClipboardList, text: 'Offboard an employee' },
    { label: 'Disable User', icon: faShieldHalved, text: 'Disable a user account' },
    { label: 'Reinstate User', icon: faShieldHalved, text: 'Reinstate a disabled user' },
    { label: 'List Users', icon: faChartLine, text: 'Show all users' },
    { label: 'List Policies', icon: faClipboardList, text: 'Show all policies' },
    { label: 'Create Policy', icon: faPlus, text: 'Create a new policy' },
    { label: 'Delete Policy', icon: faClipboardList, text: 'Delete a policy' },
    { label: 'Edit Policy', icon: faGear, text: 'Update an existing policy' },
  ];

  const currentActions = isAdmin ? ADMIN_ACTIONS : (isHR ? HR_ACTIONS : USER_ACTIONS);

  const sendMessage = async (text) => {
    const msg = text || input.trim();
    if (!msg || loading) return;
    setInput('');
    const userMsg = { role: 'user', text: msg };
    const historyWithNew = [...messages, userMsg];
    setMessages(prev => [...prev, userMsg]);
    setLoading(true);

    try {
      const res = await fetch(`${API}/api/chatbot/query`, {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          query: msg,
          history: historyWithNew.slice(-12).map(m => ({
            role: m.role === 'bot' ? 'assistant' : 'user',
            content: m.text
          }))
        })
      });
      if (res.status === 401) {
        setMessages(prev => prev.filter(m => m.text)); // Remove any undefined text messages
        if (refreshAccess) refreshAccess();
        setLoading(false);
        setTimeout(() => inputRef.current?.focus(), 10);
        return;
      }
      const data = await res.json();
      setMessages(prev => [...prev, { role: 'bot', text: data.response || "I didn't get a response." }]);
      if (refreshAccess) refreshAccess();
    } catch (e) {
      setMessages(prev => [...prev, { role: 'bot', text: "⚠️ Couldn't reach the IAM backend. Is the server running?" }]);
    }
    setLoading(false);
    setTimeout(() => inputRef.current?.focus(), 10);
  };

  return (
    <div className="flex h-full">
      <div className="flex-1 flex flex-col h-full bg-bg">
        <div className="px-7 py-5 border-b border-border-subtle bg-surface flex items-center gap-3.5">
          <FontAwesomeIcon icon={faShield} className="text-2xl opacity-90" />
          <div>
            <h2 className="text-base font-semibold">
              IAM AI Assistant 
              {isAdmin && <span className="ml-2 text-[10px] bg-accent-blue text-white px-2 py-0.5 rounded font-bold uppercase tracking-wide align-middle">Admin Mode</span>}
              {isHR && <span className="ml-2 text-[10px] bg-emerald-500 text-white px-2 py-0.5 rounded font-bold uppercase tracking-wide align-middle">HR Mode</span>}
            </h2>
            <p className="text-xs text-text-muted mt-0.5">
              {(isAdmin || isHR)
                ? `👋 Hi, ${user.full_name?.split(' ')[0] || user.username}! Ready to manage identities & access.`
                : `👋 Hi, ${user.full_name?.split(' ')[0] || user.username}! Ask about access, VPN, or IAM policies.`}
            </p>

          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-7 py-7 flex flex-col gap-5">
          {messages.map((m, i) => (
            <div key={i} className={`flex gap-3 max-w-[75%] ${m.role === 'user' ? 'self-end flex-row-reverse' : 'self-start'}`}>
              <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 text-sm ${m.role === 'bot' ? 'bg-elevated border border-border' : 'bg-accent-blue text-white font-semibold text-xs'}`}>
                {m.role === 'bot' ? <FontAwesomeIcon icon={faShield} /> : (user.username ? user.username[0].toUpperCase() : 'U')}
              </div>
              <div
                className={`px-4 py-3 rounded-2xl text-sm leading-relaxed ${m.role === 'bot' ? 'bg-elevated border border-border rounded-bl-md' : 'bg-accent-blue text-white rounded-br-md'}`}
                dangerouslySetInnerHTML={{ __html: renderMarkdown(m.text) }}
              />
            </div>
          ))}
          {loading && (
            <div className="flex gap-3 max-w-[75%]">
              <div className="w-8 h-8 rounded-full bg-elevated border border-border flex items-center justify-center text-sm"><FontAwesomeIcon icon={faShield} /></div>
              <div className="px-4 py-3 rounded-2xl bg-elevated border border-border rounded-bl-md">
                <div className="flex gap-1.5 items-center">
                  <div className="w-1.5 h-1.5 rounded-full bg-text-muted animate-bounce" />
                  <div className="w-1.5 h-1.5 rounded-full bg-text-muted animate-bounce" style={{ animationDelay: '0.15s' }} />
                  <div className="w-1.5 h-1.5 rounded-full bg-text-muted animate-bounce" style={{ animationDelay: '0.3s' }} />
                </div>
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        <div className="px-7 pb-4 flex flex-wrap gap-2">
          {currentActions.map((a, i) => (
            <button 
              key={i} 
              className="px-3.5 py-2 rounded-full text-xs font-medium bg-elevated border border-border text-text-secondary transition-all duration-150 hover:bg-hover hover:text-text cursor-pointer disabled:opacity-50 flex items-center gap-2"
              onClick={() => sendMessage(a.text)} 
              disabled={loading}
            >
              <FontAwesomeIcon icon={a.icon} />
              {a.label}
            </button>
          ))}
        </div>

        <div className="px-7 py-5 border-t border-border-subtle bg-surface flex gap-3">
          <input
            ref={inputRef}
            id="chat-input"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && sendMessage()}
            placeholder={(isAdmin || isHR) ? "Ask for audit reports, policy analysis, or employee changes..." : "Ask about VPN access, request permissions, enter OTP..."}
            disabled={loading}
            autoFocus
            onClick={(e) => e.stopPropagation()}
            className="flex-1 bg-elevated border-2 border-border rounded-lg px-4 py-3.5 text-sm text-text outline-none transition-all duration-200 focus:border-accent-blue focus:ring-4 focus:ring-accent-blue/20 focus:shadow-[0_0_15px_rgba(59,130,246,0.15)] placeholder:text-text-muted"
          />
          <button 
            id="chat-send"
            className="w-11 h-11 shrink-0 rounded-lg bg-accent-blue text-white border-none text-lg cursor-pointer transition-all duration-200 hover:bg-blue-600 hover:-translate-y-0.5 hover:shadow-md disabled:opacity-40 disabled:cursor-default disabled:translate-y-0 flex items-center justify-center"
            onClick={() => sendMessage()} 
            disabled={loading || !input.trim()}
          >
            <FontAwesomeIcon icon={faPaperPlane} />
          </button>
        </div>
      </div>
    </div>
  );
}
