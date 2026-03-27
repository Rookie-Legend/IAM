import React from 'react';
import VPNDashboard from './VPNDashboard';

const VPNCenter = ({ user, token, setVpnMark, vpnMark }) => {
    return (
        <div className={`unified-lab ${vpnMark ? 'active' : 'initial'}`} style={{
            height: 'calc(100vh - 60px)',
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            padding: '15px',
            background: 'var(--bg-app)',
            overflow: 'hidden'
        }}>
            <div className="vpn-section" style={{ 
                width: '100%',
                maxWidth: '600px',
                display: 'flex', 
                justifyContent: 'center',
                alignItems: 'center'
            }}>
                <div style={{ width: '100%' }}>
                    <VPNDashboard user={user} token={token} setVpnMark={setVpnMark} vpnMark={vpnMark} />
                </div>
            </div>
        </div>
    );
};

export default VPNCenter;
