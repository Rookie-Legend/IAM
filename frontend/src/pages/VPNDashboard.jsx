import React, { useState, useEffect } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faShieldHalved, faLock, faArrowsRotate, faDownload, faBan } from '@fortawesome/free-solid-svg-icons';
import { apiUrl } from '../stores/configStore';

const VPNDashboard = ({ user, token, setVpnMark, vpnMark }) => {
    const [vpns, setVpns] = useState([]);
    const [loading, setLoading] = useState(false);
    const [loadingVpn, setLoadingVpn] = useState(null);
    const [vpnStatus, setVpnStatus] = useState({
        is_connected: false,
        connected_vpn: null,
        connected_ip: null
    });

    useEffect(() => {
        if (user && token) {
            fetchVpns();
        }
    }, [user, token]);

    useEffect(() => {
        const checkVpnStatus = async () => {
            try {
                const res = await fetch(apiUrl('/api/vpn/my-status'), {
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                if (res.ok) {
                    const data = await res.json();
                    setVpnStatus(data);
                    if (data.is_connected) {
                        if (!vpnMark) setVpnMark(true);
                    } else {
                        setVpnMark(null);
                    }
                }
            } catch (err) {
                console.error('Failed to fetch VPN status:', err);
            }
        };

        checkVpnStatus();
        const interval = setInterval(checkVpnStatus, 5000);
        return () => clearInterval(interval);
    }, [token, vpnMark]);

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

    const downloadProfile = async (vpnId) => {
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
                return true;
            } else {
                const errorData = await dlRes.json();
                alert(errorData.detail || 'Download failed');
                return false;
            }
        } catch (err) {
            alert('Failed to download profile');
            return false;
        }
    };

    const handleProvision = async (vpnId) => {
        setLoadingVpn(vpnId);
        try {
            const res = await fetch(apiUrl(`/api/vpn/provision/${vpnId}`), {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` }
            });
            const data = await res.json();
            
            if (res.status === 409) {
                handleSwitch(vpnId);
                return;
            }
            
            if (res.ok) {
                await downloadProfile(vpnId);
                fetchVpns();
            } else {
                alert(data.detail || 'Provision failed');
            }
        } catch (err) {
            alert('Failed to reach server');
        } finally {
            setLoadingVpn(null);
        }
    };

    const handleSwitch = async (vpnId) => {
        if (!confirm(`Switch from ${vpnStatus.connected_vpn} to ${vpnId}? Your current VPN will be disconnected.`)) {
            return;
        }
        
        setLoadingVpn(vpnId);
        try {
            const res = await fetch(apiUrl(`/api/vpn/switch/${vpnId}`), {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` }
            });
            const data = await res.json();
            
            if (res.ok) {
                await downloadProfile(vpnId);
                fetchVpns();
                setVpnStatus({
                    is_connected: true,
                    connected_vpn: vpnId,
                    connected_ip: data.ip
                });
            } else {
                alert(data.detail || 'Switch failed');
            }
        } catch (err) {
            alert('Failed to switch VPN');
        } finally {
            setLoadingVpn(null);
        }
    };

    const handleDownload = async (vpnId) => {
        setLoadingVpn(vpnId);
        try {
            await downloadProfile(vpnId);
        } finally {
            setLoadingVpn(null);
        }
    };

    const handleRevokeAccess = async (vpnId) => {
        if (!confirm(`Are you sure you want to revoke your VPN access for ${vpnId}? You will need to request access again from an administrator.`)) {
            return;
        }
        
        setLoadingVpn('revoke');
        try {
            const res = await fetch(apiUrl('/api/vpn/disconnect'), {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` }
            });
            
            if (res.ok) {
                setVpnStatus({
                    is_connected: false,
                    connected_vpn: null,
                    connected_ip: null
                });
                fetchVpns();
                setVpnMark(null);
                alert('VPN access has been revoked.');
            } else {
                const data = await res.json();
                alert(data.detail || 'Failed to revoke access');
            }
        } catch (err) {
            alert('Failed to revoke access');
        } finally {
            setLoadingVpn(null);
        }
    };

    const getButtonConfig = (vpn) => {
        if (!vpn.accessible) {
            return { text: 'Locked', icon: faLock, className: 'bg-elevated/50 border border-border-subtle text-text-secondary opacity-50 cursor-not-allowed', disabled: true };
        }
        
        if (vpn.is_current) {
            return { text: 'Current', icon: faShieldHalved, className: 'bg-success/20 border border-success/30 text-success cursor-pointer', disabled: false, action: () => handleDownload(vpn.id) };
        }
        
        if (vpn.has_active) {
            return { text: `Switch to ${vpn.name.split(' ')[0]}`, icon: faArrowsRotate, className: 'bg-warning/20 border border-warning/30 text-warning hover:bg-warning/30 cursor-pointer', disabled: false, action: () => handleSwitch(vpn.id) };
        }
        
        return { text: 'Download', icon: faDownload, className: 'bg-accent-blue text-white hover:bg-blue-600 cursor-pointer', disabled: false, action: () => handleProvision(vpn.id) };
    };

    const currentVpn = vpns.find(v => v.is_current);

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
                        <span className={`w-2 h-2 rounded-full ${vpnStatus.is_connected ? 'bg-success' : 'bg-error animate-pulse'}`}></span>
                        <span className={`text-sm font-semibold ${vpnStatus.is_connected ? 'text-success' : 'text-error'}`}>
                            {vpnStatus.is_connected ? 'CONNECTED' : 'DISCONNECTED'}
                        </span>
                        {vpnStatus.is_connected && vpnStatus.connected_vpn && (
                            <span className="text-xs text-text-muted ml-2">
                                ({vpnStatus.connected_vpn} - {vpnStatus.connected_ip})
                            </span>
                        )}
                    </div>
                    
                    {currentVpn && (
                        <div className="mb-4 space-y-2">
                            <div className="p-2 bg-success/10 border border-success/20 rounded-lg">
                                <p className="text-xs text-success font-medium">
                                    You have an active VPN configuration. Download it to connect.
                                </p>
                            </div>
                            <button
                                onClick={() => handleRevokeAccess(currentVpn.id)}
                                disabled={loadingVpn !== null}
                                className="w-full py-2 px-4 bg-error/10 border border-error/30 text-error rounded-lg text-sm font-medium hover:bg-error/20 transition-all flex items-center justify-center gap-2"
                            >
                                <FontAwesomeIcon icon={faBan} className="text-sm" />
                                {loadingVpn === 'revoke' ? 'Revoking...' : 'Revoke Access'}
                            </button>
                        </div>
                    )}
                    
                    <p className="text-xs text-text-muted mb-5">Available VPN profiles for your account:</p>

                    {vpns.length === 0 ? (
                        <p className="text-sm text-text-muted py-4">No VPN access configured.<br />Contact your administrator.</p>
                    ) : (
                        <div className="flex flex-col gap-2.5">
                            {vpns.map(vpn => {
                                const btnConfig = getButtonConfig(vpn);
                                return (
                                    <button
                                        key={vpn.id}
                                        className={`w-full py-3.5 px-4 rounded-xl text-sm font-semibold transition-all flex items-center justify-between group ${btnConfig.className}`}
                                        onClick={btnConfig.disabled ? undefined : btnConfig.action}
                                        disabled={loadingVpn !== null}
                                    >
                                        <div className="flex items-center gap-3">
                                            <div className="w-8 h-8 rounded-lg bg-current/10 flex items-center justify-center">
                                                <FontAwesomeIcon icon={btnConfig.icon} className="text-sm" />
                                            </div>
                                            <div className="text-left">
                                                <div className="font-semibold">{vpn.name}</div>
                                                <div className="text-[10px] opacity-70">{vpn.description}</div>
                                            </div>
                                        </div>
                                        <span className="text-[10px] px-2.5 py-1 rounded-full bg-current/10">
                                            {loadingVpn === vpn.id ? 'Loading...' : btnConfig.text}
                                        </span>
                                    </button>
                                );
                            })}
                        </div>
                    )}
                </div>

                <p className="text-[11px] text-text-muted/50">* Access is governed by CorpOD IAM policies</p>
            </div>
        </div>
    );
};

export default VPNDashboard;