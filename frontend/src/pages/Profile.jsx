import React, { useState, useEffect } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faShieldHalved,
  faUsers,
  faClockRotateLeft,
  faShield
} from '@fortawesome/free-solid-svg-icons';
import { apiUrl } from '../stores/configStore';

const Profile = ({ user, token, accessState }) => {
  const [deptMembers, setDeptMembers] = useState([]);
  const [vpns, setVpns] = useState([]);

  useEffect(() => {
    fetch(apiUrl('/api/users/department/members'), {
      headers: { 'Authorization': `Bearer ${token}` }
    })
      .then(res => res.ok ? res.json() : [])
      .then(data => {
        const all = Array.isArray(data) ? data : [];
        setDeptMembers(all);
      })
      .catch(() => setDeptMembers([]));

    // Fetch available VPNs from API like VPNDashboard
    fetch(apiUrl('/api/vpn/available'), {
      headers: { 'Authorization': `Bearer ${token}` }
    })
      .then(res => res.ok ? res.json() : [])
      .then(data => {
        setVpns(Array.isArray(data) ? data : []);
      })
      .catch(() => setVpns([]));
  }, [user, token]);

  return (
    <div className="p-10 text-text max-w-6xl mx-auto h-full overflow-y-auto animate-fade-in">
      <header className="mb-10 flex justify-between items-end">
        <div>
          <h1 className="text-3xl font-bold mb-2.5">My Security Profile</h1>
          <p className="opacity-70">Manage your IAM identity and active access grants.</p>
        </div>
        <div className="text-right">
          <span className="inline-block px-2.5 py-1 rounded-full text-[11px] font-semibold bg-accent-blue/15 text-accent-blue mb-1 mr-2">Identity Verified</span>
          <div className="text-[11px] opacity-50">Last Login: {new Date().toLocaleTimeString()}</div>
        </div>
      </header>

      <div className="grid grid-cols-[300px_1fr_280px] gap-6">
        <div className="flex flex-col gap-6">
          <section className="bg-surface border border-border-subtle rounded-xl p-7">
            <div className="text-center mb-8">
              <div className="w-24 h-24 rounded-full bg-gradient-to-br from-accent-blue to-indigo-500 mx-auto mb-5 flex items-center justify-center text-4xl font-bold">
                {(user.full_name || user.username)[0].toUpperCase()}
              </div>
              <h2 className="text-xl font-semibold mb-1">{user.full_name}</h2>
              <span className="text-xs opacity-60 uppercase tracking-wider">{user.role}</span>
            </div>

            <div className="flex flex-col gap-3.5">
              <div className="p-3 bg-elevated rounded-lg border-l-[3px] border-accent-blue">
                <span className="block text-[11px] opacity-50 mb-1">User ID</span>
                <span className="font-mono text-accent-blue text-xs">{user.user_id}</span>
              </div>
              <div className="p-3 bg-elevated rounded-lg border-l-[3px] border-accent-blue">
                <span className="block text-[11px] opacity-50 mb-1">Department</span>
                <span className="text-sm">{user.department}</span>
              </div>
              <div className="p-3 bg-elevated rounded-lg border-l-[3px] border-accent-blue">
                <span className="block text-[11px] opacity-50 mb-1">Role</span>
                <span className="text-sm">{user.role}</span>
              </div>
            </div>
          </section>

        </div>

        <div className="flex flex-col gap-6">
          <section className="bg-surface border border-border-subtle rounded-xl p-6">
            <h3 className="text-base font-semibold mb-5 flex items-center gap-2.5">
              <FontAwesomeIcon icon={faShieldHalved} /> VPN Authorization
            </h3>
            <div className="grid grid-cols-2 gap-3">
              {vpns.map(vpn => {
                const active = vpn.accessible;
                return (
                  <div
                    key={vpn.id}
                    className={`p-3 rounded-lg border transition-all ${active ? 'bg-accent-blue/8 border-accent-blue/30 shadow-[0_0_15px_rgba(59,130,246,0.3)]' : 'bg-elevated border-border-subtle opacity-60'}`}
                  >
                    <div className={`text-sm font-semibold ${active ? 'text-text' : 'text-text-muted'}`}>{vpn.name}</div>
                    <div className="text-[11px] opacity-50">{vpn.description}</div>
                  </div>
                );
              })}
            </div>
          </section>

          <section className="bg-surface border border-border-subtle rounded-xl p-5">
            <h4 className="text-xs uppercase opacity-70 mb-4"><FontAwesomeIcon icon={faUsers} className="mr-2" /> Department Members ({deptMembers.filter(m => m.user_id !== user.user_id).length})</h4>

            <div className="flex flex-col gap-2.5">
              {deptMembers.filter(m => m.user_id !== user.user_id).slice(0, 5).map(m => (
                <div key={m.user_id} className="flex items-center justify-between gap-2.5 text-sm">
                  <div className="flex items-center gap-2.5">
                    <div className="w-6 h-6 rounded-full bg-text-secondary/20 flex items-center justify-center text-[10px] text-text">
                      {m.full_name ? m.full_name[0].toUpperCase() : '?'}
                    </div>
                    <span>{m.full_name || m.user_id}</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className={`w-2 h-2 rounded-full ${m.status === 'active' ? 'bg-green-500' : 'bg-gray-400'}`}></span>
                  </div>
                </div>
              ))}
              {deptMembers.length > 6 && <div className="text-[11px] opacity-40 text-center">+ {deptMembers.length - 6} more</div>}
            </div>
          </section>
        </div>

        <div className="flex flex-col gap-6">
          <section className="bg-surface border border-border-subtle rounded-xl p-5">
            <h4 className="text-xs opacity-70 mb-4"><FontAwesomeIcon icon={faClockRotateLeft} className="mr-2" /> Recent Activity</h4>
            <div className="flex flex-col gap-3">
              <div className="text-[11px] border-l-2 border-success pl-2.5">
                <div className="opacity-50">10m ago</div>
                <div>Connected to {user.department} VPN</div>
              </div>
              <div className="text-[11px] border-l-2 border-accent-blue pl-2.5">
                <div className="opacity-50">2h ago</div>
                <div>Accessed {user.department} resources</div>
              </div>
            </div>
          </section>

          <div className="p-5 rounded-xl border border-border-subtle" style={{ background: 'linear-gradient(135deg, rgba(59,130,246,0.1), rgba(99,102,241,0.1))' }}>
            <h4 className="text-sm font-semibold mb-2.5"><FontAwesomeIcon icon={faShield} className="mr-2" /> Security Tip</h4>
            <p className="text-[12px] opacity-70 leading-relaxed">
              Your access to the <strong>{user.department}</strong> department is audited. Always disconnect your VPN when finished.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Profile;
