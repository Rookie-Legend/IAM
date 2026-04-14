import React, { useState, useEffect } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faCircle, faShieldHalved, faUserLock, faPlug, faPlugCircleXmark } from '@fortawesome/free-solid-svg-icons';
import { apiUrl } from '../stores/configStore';

const AuditDashboard = ({ token }) => {
  const [logs, setLogs] = useState([]);
  const [vpnLogs, setVpnLogs] = useState([]);
  const [filter, setFilter] = useState('');
  const [vpnFilter, setVpnFilter] = useState('');
  const [viewMode, setViewMode] = useState('system');
  const [vpnEventFilter, setVpnEventFilter] = useState('all');
  const [selectedLog, setSelectedLog] = useState(null);

  useEffect(() => {
    const fetchLogs = async () => {
      try {
        const res = await fetch(apiUrl('/api/audit/logs'), {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        const data = await res.json();
        const all = Array.isArray(data) ? data : [];
        setLogs(all);
      } catch (e) {
        console.error('Failed to fetch audit logs', e);
      }
    };
    fetchLogs();
    const interval = setInterval(fetchLogs, 8000);
    return () => clearInterval(interval);
  }, [token]);

  useEffect(() => {
    const fetchVpnLogs = async () => {
      try {
        const params = new URLSearchParams();
        if (vpnEventFilter !== 'all') {
          params.append('event_type', vpnEventFilter);
        }
        params.append('limit', '100');

        const res = await fetch(apiUrl(`/api/vpn/audit-logs?${params.toString()}`), {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        const data = await res.json();
        setVpnLogs(data.logs || []);
      } catch (e) {
        console.error('Failed to fetch VPN logs', e);
      }
    };
    fetchVpnLogs();
    const interval = setInterval(fetchVpnLogs, 10000);
    return () => clearInterval(interval);
  }, [token, vpnEventFilter]);

  const findMatchingAccessRequest = async (userId, resourceType) => {
    try {
      const res = await fetch(apiUrl('/api/admin/access-requests'), {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      const requests = await res.json();
      return requests.find(r => r.user_id === userId && r.resource_type === resourceType && r.status === 'pending');
    } catch (e) {
      console.error('Failed to fetch access requests', e);
      return null;
    }
  };

  const handleEscalateAction = async (action) => {
    if (!selectedLog || selectedLog.action !== 'ESCALATE') return;

    const request = await findMatchingAccessRequest(selectedLog.user_id, selectedLog.target_resource);
    if (!request) {
      setSelectedLog(null);
      return;
    }

    const endpoint = action === 'accept'
      ? apiUrl(`/api/admin/access-requests/${request.id}/approve`)
      : apiUrl(`/api/admin/access-requests/${request.id}/deny`);

    try {
      await fetch(endpoint, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` }
      });
      const newAction = action === 'accept' ? 'ESCALATE_ACCEPTED' : 'ESCALATE_DENIED';
      setLogs(logs.map(log =>
        log === selectedLog ? { ...log, action: newAction } : log
      ));
      setSelectedLog(null);
    } catch (e) {
      setSelectedLog(null);
    }
  };

  const displayedLogs = logs.filter(l => {
    const isAccessRequest = ['ACCEPT', 'ESCALATE', 'DENY', 'ESCALATE_ACCEPTED', 'ESCALATE_DENIED'].includes(l.action);
    const matchesMode = viewMode === 'access' ? isAccessRequest : !isAccessRequest;
    const matchesFilter = filter ? (l.user_id && l.user_id.toLowerCase().includes(filter.toLowerCase())) : true;
    return matchesMode && matchesFilter;
  });

  const displayedVpnLogs = vpnLogs.filter(l => {
    if (vpnEventFilter !== 'all' && l.event_type !== vpnEventFilter) return false;
    if (vpnFilter && l.user_id && !l.user_id.toLowerCase().includes(vpnFilter.toLowerCase())) return false;
    return true;
  });

  const decisionColor = (action) => {
    if (!action) return '';
    const act = action.toLowerCase();
    if (act.includes('grant') || act === 'joiner' || act === 'reinstate' || act === 'accept') return 'text-success bg-success/10';
    if (act.includes('revoke') || act === 'leaver' || act.includes('deny') || act.includes('lock')) return 'text-error bg-error/10';
    if (act.includes('mfa') || act === 'mover') return 'text-accent-blue bg-accent-blue/10';
    return 'text-warning bg-warning/10';
  };

  const vpnEventTypeIcon = (type) => {
    switch (type) {
      case 'connect': return faPlug;
      case 'disconnect': return faPlugCircleXmark;
      case 'suspicious_login': return faUserLock;
      case 'blocked_connect': return faShieldHalved;
      default: return faCircle;
    }
  };

  const vpnEventTypeColor = (type) => {
    switch (type) {
      case 'connect': return 'text-success bg-success/10';
      case 'disconnect': return 'text-warning bg-warning/10';
      case 'suspicious_login': return 'text-error bg-error/10';
      case 'blocked_connect': return 'text-error bg-error/10';
      default: return 'text-text-muted bg-elevated';
    }
  };

  return (
    <div className="p-7 h-full overflow-y-auto">
      <h1 className="text-2xl font-bold tracking-tight">Audit Logs & Explainability</h1>
      <p className="text-sm text-text-muted mt-1 mb-7">Immutable record of every IAM decision, policy applied, and RAG reasoning.</p>

      <div className="flex gap-2 mb-4">
        <button
          onClick={() => setViewMode('system')}
          className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${viewMode === 'system' ? 'bg-accent-blue text-white' : 'bg-surface border border-border text-text-muted hover:text-text'}`}
        >
          System Actions Log
        </button>
        <button
          onClick={() => setViewMode('access')}
          className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${viewMode === 'access' ? 'bg-accent-blue text-white' : 'bg-surface border border-border text-text-muted hover:text-text'}`}
        >
          Access Request Log
        </button>
        <button
          onClick={() => setViewMode('vpn')}
          className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${viewMode === 'vpn' ? 'bg-accent-blue text-white' : 'bg-surface border border-border text-text-muted hover:text-text'}`}
        >
          VPN Logs
        </button>
      </div>

      {viewMode === 'vpn' ? (
        <>
          <div className="bg-surface border border-border-subtle rounded-xl p-4 mb-5 flex gap-3 items-center flex-wrap">
            <input
              className="w-48 bg-elevated border border-border rounded-md px-3.5 py-2 text-sm text-text outline-none focus:border-accent-blue focus:shadow-[0_0_0_3px_var(--color-accent-blue-muted)] placeholder:text-text-muted transition-all"
              placeholder="Filter by User ID"
              value={vpnFilter}
              onChange={e => setVpnFilter(e.target.value)}
            />
            <select
              className="bg-elevated border border-border rounded-md px-3.5 py-2 text-sm text-text outline-none focus:border-accent-blue transition-all"
              value={vpnEventFilter}
              onChange={e => setVpnEventFilter(e.target.value)}
            >
              <option value="all">All Events</option>
              <option value="connect">Connect</option>
              <option value="disconnect">Disconnect</option>
              <option value="disconnect_force">Force Disconnect</option>
              <option value="revoke">Revoke</option>
            </select>
            <span className="text-sm text-text-muted ml-auto">{displayedVpnLogs.length} records</span>
            <span className="text-xs text-success flex items-center gap-1.5">
              <FontAwesomeIcon icon={faCircle} className="text-[8px]" /> Live (auto-refresh 10s)
            </span>
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
                  {displayedVpnLogs.length === 0 && (
                    <tr>
                      <td colSpan={6} className="text-center p-8 text-text-muted">
                        No VPN logs found.
                      </td>
                    </tr>
                  )}
                  {displayedVpnLogs.map((log, idx) => (
                    <tr
                      key={`${log.user_id}-${log.timestamp}-${idx}`}
                      className="border-b border-border-subtle hover:bg-hover transition-colors cursor-pointer"
                      onClick={() => setSelectedLog({ ...log, isVpnLog: true })}
                    >
                      <td className="p-3 whitespace-nowrap text-text-muted text-[12px]">
                        {new Date(log.timestamp).toLocaleString()}
                      </td>
                      <td className="p-3">
                        <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold ${vpnEventTypeColor(log.event_type)}`}>
                          <FontAwesomeIcon icon={vpnEventTypeIcon(log.event_type)} className="text-[10px]" />
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
                        {log.details || '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      ) : (
        <>
          <div className="bg-surface border border-border-subtle rounded-xl p-4 mb-5 flex gap-3 items-center">
            <input
              className="w-56 bg-elevated border border-border rounded-md px-3.5 py-2 text-sm text-text outline-none focus:border-accent-blue focus:shadow-[0_0_0_3px_var(--color-accent-blue-muted)] placeholder:text-text-muted transition-all"
              placeholder="Filter by User ID"
              value={filter}
              onChange={e => setFilter(e.target.value)}
            />
            <span className="text-sm text-text-muted">{displayedLogs.length} records</span>
            <span className="text-xs text-success ml-auto flex items-center gap-1.5">
              <FontAwesomeIcon icon={faCircle} className="text-[8px]" /> Live (auto-refresh 8s)
            </span>
          </div>

          <div className="bg-surface border border-border-subtle rounded-xl overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-[13px]">
                <thead>
                  <tr className="bg-elevated">
                    <th className="text-left p-3 text-[11px] uppercase tracking-wide text-text-muted font-semibold border-b border-border">Timestamp</th>
                    <th className="text-left p-3 text-[11px] uppercase tracking-wide text-text-muted font-semibold border-b border-border">User</th>
                    <th className="text-left p-3 text-[11px] uppercase tracking-wide text-text-muted font-semibold border-b border-border">Action</th>
                    <th className="text-left p-3 text-[11px] uppercase tracking-wide text-text-muted font-semibold border-b border-border">Details</th>
                  </tr>
                </thead>
                <tbody>
                  {displayedLogs.length === 0 && (
                    <tr>
                      <td colSpan={4} className="text-center p-8 text-text-muted">
                        No {viewMode === 'system' ? 'system actions' : 'access requests'} found.
                      </td>
                    </tr>
                  )}
                  {displayedLogs.map((log, idx) => (
                    <tr
                      key={`${log.user_id}-${log.timestamp}-${idx}`}
                      className={`border-b border-border-subtle hover:bg-hover transition-colors ${viewMode === 'access' ? 'cursor-pointer' : ''}`}
                      onClick={() => {
                        if (viewMode === 'access') setSelectedLog(log);
                      }}
                    >
                      <td className="p-3 whitespace-nowrap text-text-muted text-[12px]">
                        {new Date(log.timestamp).toLocaleString()}
                      </td>
                      <td className="p-3">
                        <code className="text-[12px] px-1.5 py-0.5 rounded" style={{ backgroundColor: 'var(--color-code-bg)' }}>{log.user_id || '—'}</code>
                      </td>
                      <td className="p-3">
                        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-[11px] font-semibold ${decisionColor(log.action)}`}>
                          {log.action}
                        </span>
                      </td>
                      <td className="p-3 text-text-muted text-[12px] leading-relaxed whitespace-normal break-words" style={{ minWidth: '260px' }}>
                        {typeof log.details === 'object' ? JSON.stringify(log.details) : (log.details || log.target_user || '—')}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {selectedLog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center backdrop-blur-sm" style={{ backgroundColor: 'var(--color-overlay)' }} onClick={() => setSelectedLog(null)}>
          <div className="bg-surface border border-border rounded-xl p-6 max-w-2xl w-full mx-4 shadow-xl" onClick={e => e.stopPropagation()}>
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-xl font-bold">{selectedLog.isVpnLog ? 'VPN Log' : 'Access Request'} Details</h2>
              <button className="text-text-muted hover:text-text text-xl" onClick={() => setSelectedLog(null)}>×</button>
            </div>

            {selectedLog.isVpnLog ? (
              <div className="space-y-3 text-sm">
                <div className="flex gap-2">
                  <span className="text-text-muted w-24">Event:</span>
                  <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold ${vpnEventTypeColor(selectedLog.event_type)}`}>
                    <FontAwesomeIcon icon={vpnEventTypeIcon(selectedLog.event_type)} className="text-[10px]" />
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
                  <span className="text-text-muted w-24">VPN ID:</span>
                  <span className="text-text">{selectedLog.vpn_id || '—'}</span>
                </div>
                <div className="flex gap-2">
                  <span className="text-text-muted w-24">Timestamp:</span>
                  <span className="text-text">{new Date(selectedLog.timestamp).toLocaleString()}</span>
                </div>
                {selectedLog.details && (
                  <div className="mt-3 p-3 bg-elevated rounded-lg border border-border-subtle">
                    <span className="text-text-muted block mb-1">Details:</span>
                    <span className="text-text">{selectedLog.details}</span>
                  </div>
                )}
              </div>
            ) : (
              <div className="space-y-4 text-sm mt-6">
                {selectedLog.rag_details ? (
                  <>
                    <div className="mb-5 border-b border-border-subtle pb-4">
                      <span className="font-bold text-[15px] uppercase tracking-wider text-text">Decision:</span>
                      <span className={`ml-3 font-extrabold px-2.5 py-1 rounded text-[14px] ${decisionColor(selectedLog.action)}`}>{selectedLog.action}</span>
                    </div>

                    <div className="mb-5">
                      <p className="font-bold text-[15px] mb-3 uppercase tracking-wider text-text">Reason:</p>
                      <ul className="list-disc list-none space-y-2 ml-1 text-text-muted">
                        <li><strong className="text-text mr-1">— Identity Check:</strong> {selectedLog.rag_details.identity_check || 'N/A'}</li>
                        <li><strong className="text-text mr-1">— Policy Check:</strong> {selectedLog.rag_details.policy_check || 'N/A'}</li>
                        <li><strong className="text-text mr-1">— Audit Check:</strong> {selectedLog.rag_details.audit_check || 'N/A'}</li>
                      </ul>
                    </div>

                    <div className="bg-elevated p-4 rounded-lg border border-border-subtle">
                      <p className="font-bold text-[14px] mb-2 uppercase tracking-wider text-text">Explanation:</p>
                      <p className="text-text-muted leading-relaxed">{selectedLog.rag_details.explanation || 'No explanation provided.'}</p>
                    </div>
                  </>
                ) : (
                  <div className="bg-elevated rounded-lg p-4 mt-4 border border-border-subtle">
                    <p className="text-text-muted">No advanced RAG details available for this request.</p>
                    <p className="mt-2 text-[13px]">{typeof selectedLog.details === 'object' ? JSON.stringify(selectedLog.details) : selectedLog.details}</p>
                  </div>
                )}
              </div>
            )}

            <div className="mt-6 flex justify-end gap-3">
              {!selectedLog.isVpnLog && selectedLog.action === 'ESCALATE' && (
                <>
                  <button
                    onClick={() => handleEscalateAction('deny')}
                    className="px-4 py-2 bg-error text-white rounded-md text-sm font-medium hover:bg-error/90"
                  >
                    Deny
                  </button>
                  <button
                    onClick={() => handleEscalateAction('accept')}
                    className="px-4 py-2 bg-success text-white rounded-md text-sm font-medium hover:bg-success/90"
                  >
                    Accept
                  </button>
                </>
              )}
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

export default AuditDashboard;
