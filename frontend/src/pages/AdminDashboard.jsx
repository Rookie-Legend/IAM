import React, { useState, useEffect } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faTriangleExclamation,
  faPencil,
  faTrashCan,
  faUsers,
  faShieldHalved,
  faUserMinus,
  faUserPlus,
  faRightFromBracket
} from '@fortawesome/free-solid-svg-icons';

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const TYPE_COLORS = { jml: '#22c55e', access: '#3b82f6', mfa: '#f59e0b' };
const STATUS_COLORS = { active: '#22c55e', inactive: '#ef4444', disabled: '#f59e0b' };

const AdminDashboard = ({ token }) => {
  const [policies, setPolicies] = useState([]);
  const [users, setUsers] = useState([]);
  const [newPolicy, setNewPolicy] = useState({ name: '', type: 'access', description: '', department: '', vpn: '', is_active: true, json: '' });
  const [saved, setSaved] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [stats, setStats] = useState(null);
  const [activeTab, setActiveTab] = useState('users');
  const [searchTerm, setSearchTerm] = useState('');
  
  // Custom Confirmation Modal State
  const [confirmModal, setConfirmModal] = useState({
    isOpen: false,
    action: null, // 'disable', 'reinstate', 'offboard'
    userId: null,
    inputValue: ''
  });

  const authHeaders = {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${token}`
  };

  useEffect(() => {
    fetchPolicies();
    fetchStats();
    fetchUsers();
  }, []);

  const fetchPolicies = async () => {
    try {
      const res = await fetch(`${API}/api/policies/`, { headers: { 'Authorization': `Bearer ${token}` } });
      const data = await res.json();
      setPolicies(Array.isArray(data) ? data : []);
    } catch (e) {
      console.error('Fetch policies error:', e);
    }
  };

  const fetchStats = async () => {
    try {
      const res = await fetch(`${API}/api/admin/dashboard`, { headers: { 'Authorization': `Bearer ${token}` } });
      if (res.ok) setStats(await res.json());
    } catch (e) { }
  };

  const fetchUsers = async () => {
    try {
      const res = await fetch(`${API}/api/admin/users`, { headers: authHeaders });
      if (res.ok) {
        const data = await res.json();
        setUsers(Array.isArray(data) ? data : []);
      }
    } catch (e) { }
  };

  const handleSave = async () => {
    if (!newPolicy.name || !newPolicy.description) {
      alert('Please fill in name and description');
      return;
    }

    const url = editingId ? `${API}/api/policies/${editingId}` : `${API}/api/policies`;
    const method = editingId ? 'PUT' : 'POST';

    await fetch(url, { method, headers: authHeaders, body: JSON.stringify(newPolicy) });
    setSaved(true);
    setNewPolicy({ name: '', type: 'access', description: '', department: '', vpn: '', is_active: true, json: '' });
    setEditingId(null);
    fetchPolicies();
    setTimeout(() => setSaved(false), 2000);
  };

  const handleEdit = (p) => {
    setEditingId(p._id);
    setNewPolicy({ 
      name: p.name, 
      type: p.type, 
      description: p.description, 
      department: p.department || '', 
      vpn: p.vpn || '', 
      is_active: p.is_active,
      json: '' 
    });
  };

  const handleDelete = async (id) => {
    if (!window.confirm('Delete this policy?')) return;
    await fetch(`${API}/api/policies/${id}`, { method: 'DELETE', headers: { 'Authorization': `Bearer ${token}` } });
    fetchPolicies();
  };

  const handleUserActionClick = (userId, action) => {
    setConfirmModal({
      isOpen: true,
      action,
      userId,
      inputValue: ''
    });
  };

  const handleConfirmAction = async () => {
    if (confirmModal.inputValue !== 'YES') {
      alert('You must type YES to confirm.');
      return;
    }
    
    const { userId, action } = confirmModal;
    setConfirmModal({ isOpen: false, action: null, userId: null, inputValue: '' });
    
    try {
      await fetch(`${API}/api/admin/users/${userId}/${action}`, { method: 'POST', headers: authHeaders });
      fetchUsers();
      fetchStats();
    } catch (err) {
      console.error('Failed to perform action', err);
    }
  };

  const cancelConfirm = () => {
    setConfirmModal({ isOpen: false, action: null, userId: null, inputValue: '' });
  };

  const filteredUsers = users.filter(u => {
    const term = searchTerm.toLowerCase();
    return (
      (u._id || '').toLowerCase().includes(term) ||
      (u.full_name || '').toLowerCase().includes(term) ||
      (u.department || '').toLowerCase().includes(term) ||
      (u.role || '').toLowerCase().includes(term) ||
      (u.email || '').toLowerCase().includes(term)
    );
  });

  return (
    <div className="p-7 h-full overflow-y-auto">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Admin Dashboard</h1>
          <p className="text-sm text-text-muted mt-1">Manage users, policies, and system settings.</p>
        </div>
      </div>

      {/* Live Stats */}
      {stats && (
        <div className="grid grid-cols-4 gap-4 mb-7">
          {[
            { label: 'Total Users', value: stats.total_users, icon: faUsers },
            { label: 'Active Users', value: stats.active_users, icon: faUserPlus, color: '#22c55e' },
            { label: 'Disabled', value: stats.disabled_users, icon: faUserMinus, color: '#f59e0b' },
            { label: 'Policies', value: policies.length, icon: faShieldHalved },
          ].map(s => (
            <div key={s.label} className="bg-surface border border-border-subtle rounded-xl p-4 text-center">
              <div className="text-2xl font-bold" style={{ color: s.color || 'var(--accent-blue)' }}>{s.value}</div>
              <div className="text-xs text-text-muted mt-1">{s.label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-2 mb-6 border-b border-border-subtle pb-2">
        {[
          { id: 'users', label: 'Users', icon: faUsers },
          { id: 'policies', label: 'Policies', icon: faShieldHalved },
        ].map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
              activeTab === tab.id
                ? 'bg-accent-blue text-white'
                : 'text-text-muted hover:bg-white/10 hover:text-text'
            }`}
          >
            <FontAwesomeIcon icon={tab.icon} />
            {tab.label}
          </button>
        ))}
      </div>

      {/* Users Tab */}
      {activeTab === 'users' && (
        <div>
          {/* Search */}
          <div className="mb-4">
            <input
              type="text"
              placeholder="Search by ID, name, department, role, or email..."
              value={searchTerm}
              onChange={e => setSearchTerm(e.target.value)}
              className="w-full bg-elevated border border-border rounded-md px-4 py-2.5 text-sm text-text outline-none focus:border-accent-blue"
            />
          </div>

          {/* Users Table */}
          <div className="bg-surface border border-border-subtle rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-elevated border-b border-border-subtle">
                <tr>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-text-muted uppercase tracking-wide">User ID</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-text-muted uppercase tracking-wide">Name</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-text-muted uppercase tracking-wide">Department</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-text-muted uppercase tracking-wide">Role</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-text-muted uppercase tracking-wide">Status</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-text-muted uppercase tracking-wide">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredUsers.map(u => (
                  <tr key={u._id} className="border-b border-border-subtle hover:bg-white/5 transition-all">
                    <td className="px-4 py-3 font-mono text-xs">{u._id}</td>
                    <td className="px-4 py-3">
                      <div className="font-medium">{u.full_name || 'N/A'}</div>
                      <div className="text-xs text-text-muted">{u.email}</div>
                    </td>
                    <td className="px-4 py-3">{u.department || 'N/A'}</td>
                    <td className="px-4 py-3">{u.role || 'N/A'}</td>
                    <td className="px-4 py-3">
                      <span
                        className="px-2 py-1 rounded-full text-xs font-semibold"
                        style={{
                          backgroundColor: `${STATUS_COLORS[u.status] || '#888'}20`,
                          color: STATUS_COLORS[u.status] || '#888'
                        }}
                      >
                        {u.status || 'unknown'}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex gap-2">
                        {u.disabled ? (
                          <button
                            onClick={() => handleUserActionClick(u._id, 'reinstate')}
                            className="px-3 py-1.5 rounded text-xs font-semibold bg-green-500/20 text-green-400 hover:bg-green-500/30 transition-all flex items-center gap-1"
                            title="Reinstate user"
                          >
                            <FontAwesomeIcon icon={faUserPlus} />
                            Reinstate
                          </button>
                        ) : (
                          <>
                            <button
                              onClick={() => handleUserActionClick(u._id, 'disable')}
                              className="px-3 py-1.5 rounded text-xs font-semibold bg-yellow-500/20 text-yellow-400 hover:bg-yellow-500/30 transition-all flex items-center gap-1"
                              title="Disable user"
                            >
                              <FontAwesomeIcon icon={faUserMinus} />
                              Disable
                            </button>
                            <button
                              onClick={() => handleUserActionClick(u._id, 'offboard')}
                              className="px-3 py-1.5 rounded text-xs font-semibold bg-red-500/20 text-red-400 hover:bg-red-500/30 transition-all flex items-center gap-1"
                              title="Offboard user"
                            >
                              <FontAwesomeIcon icon={faRightFromBracket} />
                              Offboard
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
                {filteredUsers.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-4 py-8 text-center text-text-muted">
                      {searchTerm ? 'No users match your search.' : 'No users found.'}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Policies Tab */}
      {activeTab === 'policies' && (
        <div className="grid grid-cols-2 gap-5">
          {/* Policy Form */}
          <div className="bg-surface border border-border-subtle rounded-xl p-6">
            <h3 className="text-base font-semibold mb-4">{editingId ? 'Edit Policy' : 'Create New Policy'}</h3>
            <div className="flex flex-col gap-4">
              <div>
                <label className="block text-xs text-text-muted mb-1.5 font-medium">Name</label>
                <input placeholder="e.g. HR VPN Policy"
                  value={newPolicy.name}
                  onChange={e => setNewPolicy({ ...newPolicy, name: e.target.value })}
                  className="w-full bg-elevated border border-border rounded-md px-3.5 py-2.5 text-sm text-text outline-none focus:border-accent-blue" />
              </div>
              <div>
                <label className="block text-xs text-text-muted mb-1.5 font-medium">Description</label>
                <input placeholder="e.g. VPN access for HR personnel"
                  value={newPolicy.description}
                  onChange={e => setNewPolicy({ ...newPolicy, description: e.target.value })}
                  className="w-full bg-elevated border border-border rounded-md px-3.5 py-2.5 text-sm text-text outline-none focus:border-accent-blue" />
              </div>
              <div>
                <label className="block text-xs text-text-muted mb-1.5 font-medium">Type</label>
                <select value={newPolicy.type} onChange={e => setNewPolicy({ ...newPolicy, type: e.target.value })}
                  className="w-full bg-elevated border border-border rounded-md px-3.5 py-2.5 text-sm text-text outline-none focus:border-accent-blue">
                  <option value="access">Access</option>
                  <option value="jml">JML</option>
                  <option value="mfa">MFA</option>
                </select>
              </div>
              <div>
                <label className="block text-xs text-text-muted mb-1.5 font-medium">JSON</label>
                <textarea
                  placeholder='{"department": "HR", "vpn": "vpn_hr"}'
                  value={newPolicy.json || ''}
                  onChange={e => {
                    try {
                      const parsed = JSON.parse(e.target.value);
                      setNewPolicy({ 
                        ...newPolicy, 
                        department: parsed.department || '',
                        vpn: parsed.vpn || '',
                        is_active: parsed.is_active !== undefined ? parsed.is_active : true,
                        json: e.target.value
                      });
                    } catch {
                      setNewPolicy({ ...newPolicy, json: e.target.value });
                    }
                  }}
                  className="w-full bg-elevated border border-border rounded-md px-3.5 py-2.5 text-sm text-text outline-none focus:border-accent-blue resize-none"
                  style={{ height: 80, fontFamily: 'monospace', fontSize: 12 }}
                />
              </div>
              <div className="flex gap-2.5">
                <button className="flex-1 py-2.5 bg-accent-blue text-white rounded-lg text-sm font-semibold hover:bg-blue-600 transition-all" onClick={handleSave}>
                  {saved ? '✓ Saved!' : (editingId ? 'Update Policy' : 'Save Policy')}
                </button>
                  {editingId && (
                    <button className="py-2.5 px-4 bg-white/10 text-text rounded-lg text-sm hover:bg-white/20 transition-all"
                      onClick={() => { setEditingId(null); setNewPolicy({ name: '', type: 'access', description: '', department: '', vpn: '', is_active: true, json: '' }); }}>
                      Cancel
                    </button>
                  )}
              </div>
            </div>
          </div>

          {/* Policy List */}
          <div className="bg-surface border border-border-subtle rounded-xl p-6">
            <h3 className="text-base font-semibold mb-4">Active Policies ({policies.length})</h3>
            <div className="overflow-y-auto pr-1" style={{ maxHeight: 500 }}>
              {policies.map(p => (
                <div key={p._id} className="mb-3 p-4 bg-elevated border border-border-subtle rounded-lg hover:border-border transition-all"
                  style={{ borderLeftWidth: 4, borderLeftColor: TYPE_COLORS[p.type] || '#888' }}>
                  <div className="flex justify-between items-center mb-2">
                    <span className="text-sm font-semibold">{p.name}</span>
                    <div className="flex gap-2 items-center">
                      <button className="p-1.5 rounded hover:bg-white/10 transition-all" onClick={() => handleEdit(p)}><FontAwesomeIcon icon={faPencil} /></button>
                      <button className="p-1.5 rounded hover:bg-error/10 transition-all" onClick={() => handleDelete(p._id)}><FontAwesomeIcon icon={faTrashCan} /></button>
                    </div>
                  </div>
                  <p className="text-[12px] text-text-muted mb-3">{p.description}</p>
                  <pre className="text-[11px] text-text-muted bg-black/30 p-3 rounded overflow-auto" style={{ fontFamily: 'monospace' }}>
                    {JSON.stringify({
                      id: p._id,
                      type: p.type,
                      department: p.department,
                      vpn: p.vpn
                    }, null, 2)}
                  </pre>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Custom Confirmation Modal */}
      {confirmModal.isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-surface border border-border rounded-xl shadow-2xl p-6 max-w-sm w-full outline outline-1 outline-white/10">
            <h3 className="text-lg font-bold text-text mb-2">
              {confirmModal.action === 'offboard' && 'Confirm Offboarding'}
              {confirmModal.action === 'disable' && 'Confirm Disable Action'}
              {confirmModal.action === 'reinstate' && 'Confirm Reinstatement'}
            </h3>
            
            <p className="text-sm text-text-muted mb-4 leading-relaxed">
              {confirmModal.action === 'offboard' && 'This action will offboard the selected user and revoke their access permanently.'}
              {confirmModal.action === 'disable' && 'This action will disable the selected user\'s account. The user will not be able to log in until the account is re-enabled.'}
              {confirmModal.action === 'reinstate' && 'This action will reinstate the selected user and restore their account access.'}
            </p>
            
            <p className="text-sm text-text font-medium mb-3">
              To continue, type <strong className="text-accent-blue font-bold">YES</strong> in the box below.
            </p>
            
            <input
              type="text"
              autoFocus
              className="w-full bg-elevated border border-border rounded-md px-4 py-2.5 text-sm text-text outline-none focus:border-accent-blue focus:shadow-[0_0_0_3px_var(--color-accent-blue-muted)] mb-5"
              placeholder={
                confirmModal.action === 'offboard' ? 'Type YES to confirm offboarding' :
                confirmModal.action === 'disable' ? 'Type YES to disable the account' :
                'Type YES to reinstate the account'
              }
              value={confirmModal.inputValue}
              onChange={(e) => setConfirmModal({ ...confirmModal, inputValue: e.target.value })}
              onKeyDown={(e) => e.key === 'Enter' && handleConfirmAction()}
            />
            
            <div className="flex justify-end gap-3">
              <button 
                onClick={cancelConfirm}
                className="px-4 py-2 rounded-lg text-sm font-medium text-text-muted hover:text-text hover:bg-white/5 transition-all"
              >
                Cancel
              </button>
              <button 
                onClick={handleConfirmAction}
                disabled={confirmModal.inputValue !== 'YES'}
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                  confirmModal.inputValue === 'YES' 
                    ? confirmModal.action === 'offboard' ? 'bg-red-600 text-white hover:bg-red-500' 
                      : confirmModal.action === 'disable' ? 'bg-yellow-600 text-white hover:bg-yellow-500'
                      : 'bg-green-600 text-white hover:bg-green-500'
                    : 'bg-white/10 text-white/40 cursor-not-allowed'
                }`}
              >
                {confirmModal.action === 'offboard' ? 'Confirm Offboarding' :
                 confirmModal.action === 'disable' ? 'Disable Account' :
                 'Reinstate User'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AdminDashboard;