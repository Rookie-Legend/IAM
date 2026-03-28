import React, { useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faUserPlus, faEnvelope } from '@fortawesome/free-solid-svg-icons';
import { apiUrl } from '../stores/configStore';

const AdminJoiner = ({ token }) => {
  const [formData, setFormData] = useState({
    user_id: '',
    email: '',
    full_name: '',
    department: 'Engineering',
    role: 'Engineer'
  });
  const [inviteData, setInviteData] = useState({ email: '', role: 'Engineer', department: 'Engineering' });
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setMessage(null);
    try {
      const res = await fetch(apiUrl('/api/jml/event'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          user_id: formData.user_id,
          event_type: 'joiner',
          email: formData.email,
          full_name: formData.full_name,
          department: formData.department,
          role: formData.role
        })
      });
      const data = await res.json();
      if (!res.ok) {
        setMessage({ type: 'error', text: data.detail || 'Failed to create joiner' });
      } else {
        setMessage({ type: 'success', text: `✅ ${data.message}` });
        setFormData({ user_id: '', email: '', full_name: '', department: 'Engineering', role: 'Engineer' });
      }
    } catch (err) {
      setMessage({ type: 'error', text: 'Network error or server unreachable' });
    }
    setLoading(false);
  };

  const handleInviteSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setMessage(null);
    try {
      const res = await fetch(apiUrl('/api/jml/invite'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          email: inviteData.email,
          role: inviteData.role,
          department: inviteData.department
        })
      });
      const data = await res.json();
      if (!res.ok) {
        setMessage({ type: 'error', text: data.detail || 'Failed to send invite' });
      } else {
        setMessage({ type: 'success', text: `✅ ${data.message}` });
        setInviteData({ email: '', role: 'Engineer', department: 'Engineering' });
      }
    } catch (err) {
      setMessage({ type: 'error', text: 'Network error or server unreachable' });
    }
    setLoading(false);
  };

  return (
    <div className="p-7 h-full overflow-y-auto w-full flex flex-col items-center">
      <div className="w-full max-w-2xl">
        <h1 className="text-2xl font-bold tracking-tight text-center">Onboard New Joiner</h1>
        <p className="text-sm text-text-muted mt-1 mb-8 text-center">Administratively create a new user account via JML joiner event.</p>

        {message && (
          <div className={`mb-6 p-4 rounded-xl border font-medium ${message.type === 'error' ? 'bg-error/10 border-error/50 text-error' : 'bg-success/10 border-success/50 text-success'}`}>
            {message.text}
          </div>
        )}

        <div className="bg-surface border border-border-subtle rounded-xl p-6 mb-6">
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs text-text-muted mb-1.5 font-medium">User ID (username) <span className="text-error">*</span></label>
                <input
                  required
                  placeholder="e.g. alice, bob123"
                  value={formData.user_id}
                  onChange={e => setFormData({ ...formData, user_id: e.target.value })}
                  className="w-full bg-elevated border border-border rounded-md px-3.5 py-2.5 text-sm text-text outline-none focus:border-accent-blue focus:shadow-[0_0_0_3px_var(--color-accent-blue-muted)]"
                />
              </div>
              <div>
                <label className="block text-xs text-text-muted mb-1.5 font-medium">Full Name <span className="text-error">*</span></label>
                <input
                  required
                  value={formData.full_name}
                  onChange={e => setFormData({ ...formData, full_name: e.target.value })}
                  className="w-full bg-elevated border border-border rounded-md px-3.5 py-2.5 text-sm text-text outline-none focus:border-accent-blue focus:shadow-[0_0_0_3px_var(--color-accent-blue-muted)]"
                />
              </div>
            </div>

            <div>
              <label className="block text-xs text-text-muted mb-1.5 font-medium">Email <span className="text-error">*</span></label>
              <input
                type="email"
                required
                value={formData.email}
                onChange={e => setFormData({ ...formData, email: e.target.value })}
                className="w-full bg-elevated border border-border rounded-md px-3.5 py-2.5 text-sm text-text outline-none focus:border-accent-blue focus:shadow-[0_0_0_3px_var(--color-accent-blue-muted)]"
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs text-text-muted mb-1.5 font-medium">Department <span className="text-error">*</span></label>
                <select
                  value={formData.department}
                  onChange={e => setFormData({ ...formData, department: e.target.value })}
                  className="w-full bg-elevated border border-border rounded-md px-3.5 py-2.5 text-sm text-text outline-none focus:border-accent-blue focus:shadow-[0_0_0_3px_var(--color-accent-blue-muted)]"
                >
                  <option>Engineering</option>
                  <option>Finance</option>
                  <option>HR</option>
                  <option>Security</option>
                  <option>Sales</option>
                </select>
              </div>
              <div>
                <label className="block text-xs text-text-muted mb-1.5 font-medium">Role <span className="text-error">*</span></label>
                <input
                  required
                  value={formData.role}
                  onChange={e => setFormData({ ...formData, role: e.target.value })}
                  className="w-full bg-elevated border border-border rounded-md px-3.5 py-2.5 text-sm text-text outline-none focus:border-accent-blue focus:shadow-[0_0_0_3px_var(--color-accent-blue-muted)]"
                />
              </div>
            </div>

            <p className="text-[12px] text-text-muted bg-elevated px-3 py-2 rounded-md border border-border">
              ℹ️ Temp password will be <code className="font-mono">TempPass@123</code>. The user should change it on first login.
            </p>

            <button
              type="submit"
              disabled={loading}
              className="mt-1 py-2.5 px-4 bg-accent-blue text-white rounded-lg text-sm font-semibold hover:bg-blue-600 disabled:opacity-50 transition-all flex justify-center items-center gap-2"
            >
              {loading ? 'Creating...' : <><FontAwesomeIcon icon={faUserPlus} /> Create Joiner</>}
            </button>
          </form>
        </div>

        <div className="flex items-center gap-4 mb-6">
          <div className="flex-1 h-px bg-border-subtle" />
          <span className="text-sm text-text-muted">or</span>
          <div className="flex-1 h-px bg-border-subtle" />
        </div>

        <div className="bg-surface border border-border-subtle rounded-xl p-6">
          <h3 className="text-base font-semibold mb-1 flex items-center gap-2">
            <FontAwesomeIcon icon={faEnvelope} className="text-accent-blue" />
            Send Invite via Email
          </h3>
          <p className="text-xs text-text-muted mb-4">An email with a registration link will be sent to the joiner.</p>

          <form onSubmit={handleInviteSubmit} className="flex flex-col gap-4">
            <div>
              <label className="block text-xs text-text-muted mb-1.5 font-medium">Email <span className="text-error">*</span></label>
              <input
                type="email"
                required
                placeholder="joiner@company.com"
                value={inviteData.email}
                onChange={e => setInviteData({ ...inviteData, email: e.target.value })}
                className="w-full bg-elevated border border-border rounded-md px-3.5 py-2.5 text-sm text-text outline-none focus:border-accent-blue focus:shadow-[0_0_0_3px_var(--color-accent-blue-muted)]"
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs text-text-muted mb-1.5 font-medium">Department <span className="text-error">*</span></label>
                <select
                  value={inviteData.department}
                  onChange={e => setInviteData({ ...inviteData, department: e.target.value })}
                  className="w-full bg-elevated border border-border rounded-md px-3.5 py-2.5 text-sm text-text outline-none focus:border-accent-blue focus:shadow-[0_0_0_3px_var(--color-accent-blue-muted)]"
                >
                  <option>Engineering</option>
                  <option>Finance</option>
                  <option>HR</option>
                  <option>Security</option>
                  <option>Sales</option>
                </select>
              </div>
              <div>
                <label className="block text-xs text-text-muted mb-1.5 font-medium">Role <span className="text-error">*</span></label>
                <input
                  required
                  placeholder="e.g. Engineer, Manager"
                  value={inviteData.role}
                  onChange={e => setInviteData({ ...inviteData, role: e.target.value })}
                  className="w-full bg-elevated border border-border rounded-md px-3.5 py-2.5 text-sm text-text outline-none focus:border-accent-blue focus:shadow-[0_0_0_3px_var(--color-accent-blue-muted)]"
                />
              </div>
            </div>

            <p className="text-[12px] text-text-muted bg-elevated px-3 py-2 rounded-md border border-border">
              ℹ️ An email with a registration link will be sent. The link expires in 7 days.
            </p>

            <button
              type="submit"
              disabled={loading}
              className="mt-1 py-2.5 px-4 bg-success text-white rounded-lg text-sm font-semibold hover:brightness-110 disabled:opacity-50 transition-all flex justify-center items-center gap-2"
            >
              {loading ? 'Sending...' : <><FontAwesomeIcon icon={faEnvelope} /> Send Invite Email</>}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
};

export default AdminJoiner;