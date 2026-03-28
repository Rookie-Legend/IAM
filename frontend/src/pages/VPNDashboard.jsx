import React, { useState, useEffect } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faShieldHalved, faLock } from '@fortawesome/free-solid-svg-icons';
import { apiUrl } from '../stores/configStore';

const VPNDashboard = ({ user, token, setVpnMark, vpnMark }) => {
    const [vpns, setVpns] = useState([]);
    const [loading, setLoading] = useState(false);
    const [isConnected, setIsConnected] = useState(false);

    useEffect(() => {
        if (user && token) {
            fetchVpns();
        }
    }, [user, token]);

    useEffect(() => {
        const checkVpnConnection = async () => {
            try {
                const res = await fetch('http://125.10.0.10:8000/ping');
                if (res.ok) {
                    if (!isConnected) {
                        setIsConnected(true);
                        if (!vpnMark) setVpnMark(true);
                    }
                } else {
                    if (isConnected) {
                        setIsConnected(false);
                        setVpnMark(null);
                    }
                }
            } catch (err) {
                if (isConnected) {
                    setIsConnected(false);
                    setVpnMark(null);
                }
            }
        };

        checkVpnConnection();
        const interval = setInterval(checkVpnConnection, 5000);
        return () => clearInterval(interval);
    }, [isConnected, vpnMark]);

    const fetchVpns = async () => {
        try {
            const res = await fetch(apiUrl('/api/vpn/available'), {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            const data = await res.json();
            setVpns(Array.isArray(data) ? data : []);
        } catch (err) {
            console.error('Failed to fetch VPNs:', err);
        }
    };

    const handleConnect = async (vpnId) => {
        setLoading(true);
        try {
            const res = await fetch(apiUrl(`/api/vpn/provision/${vpnId}`), {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` }
            });
            const data = await res.json();
            if (res.ok) {
                try {
                    const dlRes = await fetch(apiUrl('/api/vpn/download-profile'), {
                        headers: { 'Authorization': `Bearer ${token}` }
                    });
                    if (dlRes.ok) {
                        const blob = await dlRes.blob();
                        const url = window.URL.createObjectURL(blob);
                        const a = document.createElement('a');
                        a.href = url;
                        a.download = `${user.user_id || user.username}-${vpnId}.ovpn`;
                        document.body.appendChild(a);
                        a.click();
                        a.remove();
                        window.URL.revokeObjectURL(url);
                    }
                } catch (dlErr) {
                    console.log('Profile download skipped:', dlErr);
                }
            } else {
                alert(data.detail || 'Connection failed');
            }
        } catch (err) {
            alert('Failed to reach server');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="h-full flex items-center justify-center bg-bg p-6">
            <div className="text-center max-w-lg w-full">
                <div className="mb-8">
                    <div className="w-14 h-14 rounded-xl bg-accent-blue/20 flex items-center justify-center mx-auto mb-3">
                        <FontAwesomeIcon icon={faShieldHalved} className="text-2xl text-accent-blue" />
                    </div>
                    <h2 className="text-2xl font-bold text-text mb-2">Network Access</h2>
                    <p className="text-text-muted">User: <span className="text-text font-semibold">{user.full_name}</span> <span className="text-text-secondary">({user.department})</span></p>
                </div>

                <div className="bg-surface border border-border-subtle rounded-2xl p-5 mb-4">
                    <div className="flex items-center gap-2 mb-4 pb-3 border-b border-border-subtle">
                        <span className={`w-2 h-2 rounded-full ${isConnected ? 'bg-success' : 'bg-error animate-pulse'}`}></span>
                        <span className={`text-sm font-semibold ${isConnected ? 'text-success' : 'text-error'}`}>{isConnected ? 'CONNECTED' : 'DISCONNECTED'}</span>
                    </div>
                    <p className="text-xs text-text-muted mb-5">Available VPN profiles for your account:</p>

                    {vpns.length === 0 ? (
                        <p className="text-sm text-text-muted py-4">No VPN access configured.<br />Contact your administrator.</p>
                    ) : (
                        <div className="flex flex-col gap-2.5">
                            {vpns.map(vpn => (
                                vpn.accessible ? (
                                    <button
                                        key={vpn.id}
                                        className="w-full py-3.5 px-4 bg-accent-blue text-white rounded-xl text-sm font-semibold hover:bg-blue-600 disabled:opacity-50 transition-all flex items-center justify-between group"
                                        onClick={() => handleConnect(vpn.id)}
                                        disabled={loading}
                                    >
                                        <div className="flex items-center gap-3">
                                            <div className="w-8 h-8 rounded-lg bg-white/20 flex items-center justify-center">
                                                <FontAwesomeIcon icon={faShieldHalved} className="text-sm" />
                                            </div>
                                            <div className="text-left">
                                                <div className="font-semibold">{vpn.name}</div>
                                                <div className="text-[10px] opacity-70">{vpn.description}</div>
                                            </div>
                                        </div>
                                        <span className="text-[10px] bg-white/20 px-2.5 py-1 rounded-full group-hover:bg-white/30 transition-all">
                                            Download
                                        </span>
                                    </button>
                                ) : (
                                    <div
                                        key={vpn.id}
                                        className="w-full py-3.5 px-4 bg-elevated/50 border border-border-subtle text-text-secondary rounded-xl text-sm flex items-center justify-between opacity-50 cursor-not-allowed"
                                    >
                                        <div className="flex items-center gap-3">
                                            <div className="w-8 h-8 rounded-lg bg-text-muted/20 flex items-center justify-center">
                                                <FontAwesomeIcon icon={faLock} className="text-sm text-text-muted" />
                                            </div>
                                            <div className="text-left">
                                                <div className="font-semibold text-text-secondary">{vpn.name}</div>
                                                <div className="text-[10px] text-text-muted">{vpn.description}</div>
                                            </div>
                                        </div>
                                        <span className="text-[10px] bg-text-muted/20 px-2.5 py-1 rounded-full">
                                            Locked
                                        </span>
                                    </div>
                                )
                            ))}
                        </div>
                    )}
                </div>

                <p className="text-[11px] text-text-muted/50">* Access is governed by CorpOD IAM policies</p>
            </div>
        </div>
    );
};

export default VPNDashboard;