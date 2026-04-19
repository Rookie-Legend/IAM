import React, { useState, useEffect } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faShieldHalved, faLock, faArrowsRotate, faDownload, faBan } from '@fortawesome/free-solid-svg-icons';
import { apiUrl } from '../stores/configStore';

const VPNDashboard = ({ user, token, setVpnMark, vpnMark }) => {
    const [vpns, setVpns] = useState([]);
    const [loadingVpn, setLoadingVpn] = useState(null);
    const [switchModal, setSwitchModal] = useState({ open: false, vpnId: null });
    const [revokeModalOpen, setRevokeModalOpen] = useState(false);
    const [revokeMessage, setRevokeMessage] = useState(null);
    const [vpnStatus, setVpnStatus] = useState({
        has_provisioned: false,
        provisioned_vpn: null,
        is_connected: false,
        connected_vpn: null,
        connected_ip: null
    });

    const provisionedVpnId = vpnStatus.provisioned_vpn;
    const hasProvisionedSelection = vpnStatus.has_provisioned && Boolean(provisionedVpnId);

    useEffect(() => {
        if (user && token) {
            refreshVpnData();
        }
    }, [user, token]);

    useEffect(() => {
        if (!token) {
            return undefined;
        }

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
    }, [token, vpnMark, setVpnMark]);

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

    const fetchVpnStatus = async () => {
        try {
            const res = await fetch(apiUrl('/api/vpn/my-status'), {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (!res.ok) {
                return;
            }

            const data = await res.json();
            setVpnStatus(data);
            if (data.is_connected) {
                if (!vpnMark) setVpnMark(true);
            } else {
                setVpnMark(null);
            }
        } catch (err) {
            console.error('Failed to fetch VPN status:', err);
        }
    };

    const refreshVpnData = async () => {
        await Promise.all([fetchVpns(), fetchVpnStatus()]);
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
                await handleSwitch(vpnId);
                return;
            }
            
            if (res.ok) {
                await downloadProfile(vpnId);
                await refreshVpnData();
            } else {
                alert(data.detail || 'Provision failed');
            }
        } catch (err) {
            alert('Failed to reach server');
        } finally {
            setLoadingVpn(null);
        }
    };

    const openSwitchModal = (vpnId) => {
        setSwitchModal({ open: true, vpnId });
    };

    const closeSwitchModal = () => {
        if (loadingVpn !== null) {
            return;
        }
        setSwitchModal({ open: false, vpnId: null });
    };

    const openRevokeModal = () => {
        setRevokeMessage(null);
        setRevokeModalOpen(true);
    };

    const closeRevokeModal = () => {
        if (loadingVpn !== null) {
            return;
        }
        setRevokeModalOpen(false);
    };

    const showRevokeMessage = (type, text) => {
        setRevokeMessage({ type, text });
    };

    const handleSwitch = async (vpnId) => {
        setLoadingVpn(vpnId);
        try {
            const res = await fetch(apiUrl(`/api/vpn/switch/${vpnId}`), {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` }
            });
            const data = await res.json();
            
            if (res.ok) {
                await downloadProfile(vpnId);
                await refreshVpnData();
                closeSwitchModal();
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

    const handleRevokeConfig = async () => {
        setLoadingVpn('revoke');
        try {
            const res = await fetch(apiUrl('/api/vpn/disconnect'), {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` }
            });
            
            if (res.ok) {
                setVpnStatus({
                    has_provisioned: false,
                    provisioned_vpn: null,
                    is_connected: false,
                    connected_vpn: null,
                    connected_ip: null
                });
                await refreshVpnData();
                setVpnMark(null);
                setRevokeModalOpen(false);
                showRevokeMessage('success', 'VPN config revoked. Your approved access is still available.');
            } else {
                const data = await res.json();
                showRevokeMessage('error', data.detail || 'Failed to revoke VPN config');
            }
        } catch (err) {
            showRevokeMessage('error', 'Failed to revoke VPN config');
        } finally {
            setLoadingVpn(null);
        }
    };

    const getButtonConfig = (vpn) => {
        if (!vpn.accessible) {
            return { text: 'Locked', icon: faLock, className: 'bg-elevated/50 border border-border-subtle text-text-secondary opacity-50 cursor-not-allowed', disabled: true };
        }

        if (vpn.has_provisioned && provisionedVpnId === vpn.id) {
            return {
                text: vpnStatus.is_connected ? 'Download Current Profile' : 'Download Profile',
                icon: faDownload,
                className: 'bg-success/20 border border-success/30 text-success cursor-pointer',
                disabled: false,
                action: () => handleDownload(vpn.id)
            };
        }

        if (hasProvisionedSelection) {
            return {
                text: `Switch to ${vpn.name.split(' ')[0]}`,
                icon: faArrowsRotate,
                className: 'bg-accent-blue text-white hover:bg-blue-600 cursor-pointer',
                disabled: false,
                action: () => openSwitchModal(vpn.id)
            };
        }

        return {
            text: 'Provision and Download',
            icon: faDownload,
            className: 'bg-accent-blue text-white hover:bg-blue-600 cursor-pointer',
            disabled: false,
            action: () => handleProvision(vpn.id)
        };
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

                    {vpnStatus.has_provisioned && (
                        <button
                            onClick={openRevokeModal}
                            disabled={loadingVpn !== null}
                            className="w-full mt-4 py-2.5 px-4 bg-error/10 border border-error/30 text-error rounded-xl text-sm font-semibold hover:bg-error/20 transition-all flex items-center justify-center gap-2"
                        >
                            <FontAwesomeIcon icon={faBan} className="text-sm" />
                            {loadingVpn === 'revoke' ? 'Revoking...' : 'Revoke Config'}
                        </button>
                    )}
                </div>

                {revokeMessage && (
                    <div
                        className={`mb-4 rounded-xl border px-4 py-3 text-left text-sm ${
                            revokeMessage.type === 'success'
                                ? 'border-success/30 bg-success/10 text-success'
                                : 'border-error/30 bg-error/10 text-error'
                        }`}
                    >
                        {revokeMessage.text}
                    </div>
                )}

                <p className="text-[11px] text-text-muted/50">* Access is governed by CorpOD IAM policies</p>
            </div>

            {switchModal.open && (
                <div
                    className="fixed inset-0 z-50 flex items-center justify-center backdrop-blur-sm p-4"
                    style={{ backgroundColor: 'var(--color-overlay)' }}
                    onClick={closeSwitchModal}
                >
                    <div
                        className="w-full max-w-md rounded-2xl border border-border-subtle bg-surface p-6 text-left shadow-xl"
                        onClick={(e) => e.stopPropagation()}
                    >
                        <h3 className="text-lg font-bold text-text">Switch VPN Profile</h3>
                        <p className="mt-2 text-sm text-text-muted">
                            Switch from {vpnStatus.provisioned_vpn || vpnStatus.connected_vpn || 'your current VPN'} to {switchModal.vpnId}?
                            The currently provisioned profile will be revoked and replaced.
                        </p>
                        <div className="mt-6 flex justify-end gap-3">
                            <button
                                onClick={closeSwitchModal}
                                disabled={loadingVpn !== null}
                                className="rounded-xl border border-border-subtle px-4 py-2 text-sm font-semibold text-text-muted transition-all hover:bg-hover disabled:opacity-50"
                            >
                                Cancel
                            </button>
                            <button
                                onClick={() => handleSwitch(switchModal.vpnId)}
                                disabled={loadingVpn !== null}
                                className="rounded-xl bg-accent-blue px-4 py-2 text-sm font-semibold text-white transition-all hover:bg-blue-600 disabled:opacity-50"
                            >
                                {loadingVpn === switchModal.vpnId ? 'Switching...' : 'Confirm Switch'}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {revokeModalOpen && (
                <div
                    className="fixed inset-0 z-50 flex items-center justify-center backdrop-blur-sm p-4"
                    style={{ backgroundColor: 'var(--color-overlay)' }}
                    onClick={closeRevokeModal}
                >
                    <div
                        className="w-full max-w-md rounded-2xl border border-border-subtle bg-surface p-6 text-left shadow-xl"
                        onClick={(e) => e.stopPropagation()}
                    >
                        <div className="mb-4 flex items-center gap-3">
                            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-error/10 text-error">
                                <FontAwesomeIcon icon={faBan} className="text-sm" />
                            </div>
                            <div>
                                <h3 className="text-lg font-bold text-text">Revoke VPN Config</h3>
                                <p className="text-xs text-text-muted">Your IAM permission will remain active.</p>
                            </div>
                        </div>

                        <p className="text-sm leading-6 text-text-muted">
                            This removes the current generated VPN profile and disconnects the active session if one exists.
                            You can provision another approved VPN profile after this completes.
                        </p>

                        {revokeMessage?.type === 'error' && (
                            <div className="mt-4 rounded-xl border border-error/30 bg-error/10 px-4 py-3 text-sm text-error">
                                {revokeMessage.text}
                            </div>
                        )}

                        <div className="mt-6 flex justify-end gap-3">
                            <button
                                onClick={closeRevokeModal}
                                disabled={loadingVpn !== null}
                                className="rounded-xl border border-border-subtle px-4 py-2 text-sm font-semibold text-text-muted transition-all hover:bg-hover disabled:opacity-50"
                            >
                                Cancel
                            </button>
                            <button
                                onClick={handleRevokeConfig}
                                disabled={loadingVpn !== null}
                                className="rounded-xl bg-error px-4 py-2 text-sm font-semibold text-white transition-all hover:opacity-90 disabled:opacity-50"
                            >
                                {loadingVpn === 'revoke' ? 'Revoking...' : 'Revoke Config'}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default VPNDashboard;
