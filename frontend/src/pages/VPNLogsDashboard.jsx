import React, { useState, useEffect } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faCircle, faShieldHalved, faUserLock, faPlug, faPlugCircleXmark } from '@fortawesome/free-solid-svg-icons';
import { apiUrl } from '../stores/configStore';

const VPNLogsDashboard = ({ token }) => {
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('');
  const [eventTypeFilter, setEventTypeFilter] = useState('all');
  const [selectedLog, setSelectedLog] = useState(null);

  const fetchLogs = async () => {
    try {
      const params = new URLSearchParams();
      if (eventTypeFilter !== 'all') {
        params.append('event_type', eventTypeFilter);
      }
      if (filter) {
        params.append('user_id', filter);
      }
      params.append('limit', '100');

      const res = await fetch(apiUrl(`/api/vpn/audit-logs?${params.toString()}`), {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      const data = await res.json();
      setLogs(data.logs || []);
    } catch (e) {
      console.error('Failed to fetch VPN logs', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchLogs();
    const interval = setInterval(fetchLogs, 10000);
    return () => clearInterval(interval);
  }, [token, eventTypeFilter, filter]);

  const eventTypeIcon = (type) => {
    switch (type) {
      case 'connect':
        return faPlug;
      case 'disconnect':
        return faPlugCircleXmark;
      case 'suspicious_login':
        return faUserLock;
      case 'blocked_connect':
        return faShieldHalved;
      default:
        return faCircle;
    }
  };

  const eventTypeColor = (type) => {
    switch (type) {
      case 'connect':
        return 'text-success bg-success/10';
      case 'disconnect':
        return 'text-warning bg-warning/10';
      case 'suspicious_login':
        return 'text-error bg-error/10';
      case 'blocked_connect':
        return 'text-error bg-error/10';
      default:
        return 'text-text-muted bg-elevated';
    }
  };

  const displayedLogs = logs.filter(l => {
    if (eventTypeFilter !== 'all' && l.event_type !== eventTypeFilter) return false;
    if (filter && l.user_id && !l.user_id.toLowerCase().includes(filter.toLowerCase())) return false;
    return true;
  });

  return (
    <div className="p-7 h-full overflow-y-auto">
      <div className="flex items-center justify-between mb-2">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">VPN Audit Logs</h1>
          <p className="text-sm text-text-muted mt-1">VPN connection events, suspicious logins, and security incidents.</p>
        </div>
        <span className="text-xs text-success flex items-center gap-1.5">
          <FontAwesomeIcon icon={faCircle} className="text-[8px]" /> Live (auto-refresh 10s)
        </span>
      </div>

      <div className="bg-surface border border-border-subtle rounded-xl p-4 mt-5 mb-4 flex gap-3 items-center flex-wrap">
        <input
          className="w-48 bg-elevated border border-border rounded-md px-3.5 py-2 text-sm text-text outline-none focus:border-accent-blue focus:shadow-[0_0_0_3px_var(--color-accent-blue-muted)] placeholder:text-text-muted transition-all"
          placeholder="Filter by User ID"
          value={filter}
          onChange={e => setFilter(e.target.value)}
        />
        <select
          className="bg-elevated border border-border rounded-md px-3.5 py-2 text-sm text-text outline-none focus:border-accent-blue transition-all"
          value={eventTypeFilter}
          onChange={e => setEventTypeFilter(e.target.value)}
        >
          <option value="all">All Events</option>
          <option value="connect">Connect</option>
          <option value="disconnect">Disconnect</option>
          <option value="suspicious_login">Suspicious Login</option>
          <option value="blocked_connect">Blocked</option>
        </select>
        <span className="text-sm text-text-muted ml-auto">{displayedLogs.length} records</span>
      </div>

      <div className="bg-surface border border-border-subtle rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr className="bg-elevated">
                <th className="text-left p-3 text-[11px] uppercase tracking-wide text-text-muted font-semibold border-b border-border">Timestamp</th>
                <th className="text-left p-3 text-[11px] uppercase tracking-wide text-text-muted font-semibold border-b border-border">Event</th>
                <th className="text-left p-3 text-[11px] uppercase tracking-wide text-text-muted font-semibold border-b border-border">User</th>
                <th className="text-left p-3 text-[11px] uppercase tracking-wide text-text-muted font-semibold border-b border-border">VPN IP</th>
                <th className="text-left p-3 text-[11px] uppercase tracking-wide text-text-muted font-semibold border-b border-border">Source IP</th>
                <th className="text-left p-3 text-[11px] uppercase tracking-wide text-text-muted font-semibold border-b border-border">Details</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={6} className="text-center p-8 text-text-muted">
                    Loading...
                  </td>
                </tr>
              ) : displayedLogs.length === 0 ? (
                <tr>
                  <td colSpan={6} className="text-center p-8 text-text-muted">
                    No VPN logs found.
                  </td>
                </tr>
              ) : (
                displayedLogs.map((log, idx) => (
                  <tr
                    key={`${log.user_id}-${log.timestamp}-${idx}`}
                    className="border-b border-border-subtle hover:bg-hover transition-colors cursor-pointer"
                    onClick={() => setSelectedLog(log)}
                  >
                    <td className="p-3 whitespace-nowrap text-text-muted text-[12px]">
                      {new Date(log.timestamp).toLocaleString()}
                    </td>
                    <td className="p-3">
                      <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold ${eventTypeColor(log.event_type)}`}>
                        <FontAwesomeIcon icon={eventTypeIcon(log.event_type)} className="text-[10px]" />
                        {log.event_type}
                      </span>
                    </td>
                    <td className="p-3">
                      <code className="text-[12px] px-1.5 py-0.5 rounded" style={{ backgroundColor: 'var(--color-code-bg)' }}>{log.user_id || '—'}</code>
                    </td>
                    <td className="p-3 text-text-muted text-[12px]">
                      {log.vpn_ip || '—'}
                    </td>
                    <td className="p-3 text-text-muted text-[12px]">
                      {log.source_ip || '—'}
                    </td>
                    <td className="p-3 text-text-muted text-[12px] max-w-xs truncate">
                      {log.details || (log.target_user_id ? `Target: ${log.target_user_id}` : '—')}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {selectedLog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center backdrop-blur-sm" style={{ backgroundColor: 'var(--color-overlay)' }} onClick={() => setSelectedLog(null)}>
          <div className="bg-surface border border-border rounded-xl p-6 max-w-2xl w-full mx-4 shadow-xl" onClick={e => e.stopPropagation()}>
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-xl font-bold">VPN Log Details</h2>
              <button className="text-text-muted hover:text-text text-xl" onClick={() => setSelectedLog(null)}>×</button>
            </div>

            <div className="space-y-3 text-sm">
              <div className="flex gap-2">
                <span className="text-text-muted w-24">Event:</span>
                <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold ${eventTypeColor(selectedLog.event_type)}`}>
                  <FontAwesomeIcon icon={eventTypeIcon(selectedLog.event_type)} className="text-[10px]" />
                  {selectedLog.event_type}
                </span>
              </div>
              <div className="flex gap-2">
                <span className="text-text-muted w-24">User:</span>
                <code className="px-1.5 py-0.5 rounded" style={{ backgroundColor: 'var(--color-code-bg)' }}>{selectedLog.user_id || '—'}</code>
              </div>
              <div className="flex gap-2">
                <span className="text-text-muted w-24">VPN IP:</span>
                <span className="text-text">{selectedLog.vpn_ip || '—'}</span>
              </div>
              <div className="flex gap-2">
                <span className="text-text-muted w-24">Source IP:</span>
                <span className="text-text">{selectedLog.source_ip || '—'}</span>
              </div>
              <div className="flex gap-2">
                <span className="text-text-muted w-24">Timestamp:</span>
                <span className="text-text">{new Date(selectedLog.timestamp).toLocaleString()}</span>
              </div>
              {selectedLog.target_user_id && (
                <div className="flex gap-2">
                  <span className="text-text-muted w-24">Target User:</span>
                  <code className="px-1.5 py-0.5 rounded" style={{ backgroundColor: 'var(--color-code-bg)' }}>{selectedLog.target_user_id}</code>
                </div>
              )}
              {selectedLog.details && (
                <div className="mt-3 p-3 bg-elevated rounded-lg border border-border-subtle">
                  <span className="text-text-muted block mb-1">Details:</span>
                  <span className="text-text">{selectedLog.details}</span>
                </div>
              )}
            </div>

            <div className="mt-6 flex justify-end">
              <button
                onClick={() => setSelectedLog(null)}
                className="px-4 py-2 bg-accent-blue text-white rounded-md text-sm font-medium hover:bg-accent-blue/90"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default VPNLogsDashboard;
