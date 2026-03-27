import React, { useState, useEffect } from 'react';
import { useTheme } from '../contexts/ThemeContext';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faSun, faMoon, faRocket, faEnvelope, faCheck } from '@fortawesome/free-solid-svg-icons';

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const maskEmail = (email) => {
    if (!email) return '';
    const [user, domain] = email.split('@');
    if (!domain) return email;
    const maskedUser = user.length > 4 ? user.slice(0, 4) + '***' + user.slice(-2) : user.slice(0, 2) + '***';
    return `${maskedUser}@${domain}`;
};

const LoginPage = ({ onLogin }) => {
    const { theme, toggleTheme } = useTheme();
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);

    const [inviteMode, setInviteMode] = useState(false);
    const [inviteToken, setInviteToken] = useState('');
    const [inviteData, setInviteData] = useState(null);
    const [otpStep, setOtpStep] = useState(false);
    const [otp, setOtp] = useState('');
    const [registrationStep, setRegistrationStep] = useState(false);
    const [registrationData, setRegistrationData] = useState({
        username: '',
        full_name: '',
        password: '',
        confirmPassword: ''
    });
    const [registrationSuccess, setRegistrationSuccess] = useState(false);

    useEffect(() => {
        const params = new URLSearchParams(window.location.search);
        if (params.get('invite') === 'true') {
            setInviteMode(true);
            setInviteToken(params.get('token') || '');
        }
    }, []);

    const handleSubmit = async (e) => {
        e.preventDefault();
        setLoading(true);
        setError('');
        try {
            const formData = new URLSearchParams();
            formData.append('username', username);
            formData.append('password', password);

            const res = await fetch(`${API}/api/auth/login`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: formData.toString()
            });
            const data = await res.json();
            if (!res.ok) {
                setError(data.detail || 'Login failed');
                return;
            }

            const token = data.access_token;
            const meRes = await fetch(`${API}/api/users/me`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (!meRes.ok) {
                setError('Failed to fetch user profile');
                return;
            }
            const userData = await meRes.json();
            onLogin(userData, token);
        } catch (err) {
            setError('Could not connect to server');
        } finally {
            setLoading(false);
        }
    };

    const handleVerifyToken = async (e) => {
        e.preventDefault();
        setLoading(true);
        setError('');
        try {
            const res = await fetch(`${API}/api/auth/verify-invite-token`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ token: inviteToken })
            });
            const data = await res.json();
            if (!res.ok) {
                setError(data.detail || 'Invalid or expired invite token');
                return;
            }
            setInviteData(data);

            const otpRes = await fetch(`${API}/api/auth/request-registration-otp`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ token: inviteToken })
            });
            if (!otpRes.ok) {
                const otpData = await otpRes.json();
                setError(otpData.detail || 'Failed to send OTP');
                return;
            }
            setOtpStep(true);
        } catch (err) {
            setError('Could not connect to server');
        } finally {
            setLoading(false);
        }
    };

    const handleRequestOtp = async () => {
        setLoading(true);
        setError('');
        try {
            const res = await fetch(`${API}/api/auth/request-registration-otp`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ token: inviteToken })
            });
            const data = await res.json();
            if (!res.ok) {
                setError(data.detail || 'Failed to send OTP');
                return;
            }
            setOtpStep(true);
        } catch (err) {
            setError('Could not connect to server');
        } finally {
            setLoading(false);
        }
    };

    const handleVerifyOtp = async (e) => {
        e.preventDefault();
        setLoading(true);
        setError('');
        try {
            const res = await fetch(`${API}/api/auth/verify-registration-otp`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ token: inviteToken, otp })
            });
            const data = await res.json();
            if (!res.ok) {
                setError(data.detail || 'Invalid or expired OTP');
                return;
            }
            setRegistrationStep(true);
            setOtpStep(false);
        } catch (err) {
            setError('Could not connect to server');
        } finally {
            setLoading(false);
        }
    };

    const handleRegistration = async (e) => {
        e.preventDefault();
        if (registrationData.password !== registrationData.confirmPassword) {
            setError('Passwords do not match');
            return;
        }
        setLoading(true);
        setError('');
        try {
            const res = await fetch(`${API}/api/auth/complete-registration`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    token: inviteToken,
                    username: registrationData.username,
                    full_name: registrationData.full_name,
                    password: registrationData.password
                })
            });
            const data = await res.json();
            if (!res.ok) {
                setError(data.detail || 'Registration failed');
                return;
            }
            setRegistrationSuccess(true);
        } catch (err) {
            setError('Could not connect to server');
        } finally {
            setLoading(false);
        }
    };

    if (registrationSuccess) {
        return (
            <div className="h-screen flex items-center justify-center bg-bg relative overflow-hidden">
                <button
                    onClick={toggleTheme}
                    className="absolute top-6 right-6 p-3 rounded-2xl bg-surface border border-border-subtle text-text-muted hover:bg-hover hover:text-text transition-all duration-150 z-20"
                    title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
                >
                    {theme === 'dark' ? <FontAwesomeIcon icon={faSun} /> : <FontAwesomeIcon icon={faMoon} />}
                </button>

                <div className="w-[400px] p-8 bg-surface border border-border-subtle rounded-xl shadow-lg relative z-10 text-center">
                    <div className="text-5xl mb-5 flex justify-center"><FontAwesomeIcon icon={faCheck} className="text-success" /></div>
                    <h2 className="text-2xl font-bold mb-3">Registration Complete!</h2>
                    <p className="text-sm text-text-muted mb-6">Your account has been created. You can now login with your credentials.</p>
                    <button
                        onClick={() => window.location.href = '/'}
                        className="w-full py-3 bg-accent-blue text-white rounded-md text-sm font-semibold cursor-pointer transition-all duration-150 hover:bg-blue-600"
                    >
                        Go to Login
                    </button>
                </div>
            </div>
        );
    }

    if (inviteMode && !registrationStep && !otpStep) {
        return (
            <div className="h-screen flex items-center justify-center bg-bg relative overflow-hidden">
                <button
                    onClick={toggleTheme}
                    className="absolute top-6 right-6 p-3 rounded-2xl bg-surface border border-border-subtle text-text-muted hover:bg-hover hover:text-text transition-all duration-150 z-20"
                    title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
                >
                    {theme === 'dark' ? <FontAwesomeIcon icon={faSun} /> : <FontAwesomeIcon icon={faMoon} />}
                </button>

                <div className="w-[400px] p-8 bg-surface border border-border-subtle rounded-xl shadow-lg relative z-10">
                    <div className="text-center mb-6">
                        <div className="w-full h-[80px] overflow-hidden rounded-xl mb-4">
                            <img src="/logo.png" alt="CorpOD" className="w-full h-full object-cover" />
                        </div>
                        <h2 className="text-xl font-semibold">Complete Your Registration</h2>
                        <p className="text-xs text-text-muted mt-1">Enter your invite token to begin</p>
                    </div>

                    <form onSubmit={handleVerifyToken}>
                        <div className="mb-5">
                            <label className="block text-xs text-text-muted mb-1.5 font-medium">Invite Token</label>
                            <input
                                type="text"
                                className="w-full bg-elevated border border-border rounded-md px-3.5 py-3 text-sm text-text outline-none transition-all duration-200 focus:border-accent-blue focus:shadow-[0_0_0_3px_var(--color-accent-blue-muted)] font-mono"
                                value={inviteToken}
                                onChange={(e) => setInviteToken(e.target.value)}
                                placeholder="Paste your invite token"
                                required
                            />
                        </div>

                        {error && (
                            <div className="text-error text-sm text-center mb-4 px-3 py-2.5 bg-error/10 border border-error/20 rounded-md">
                                {error}
                            </div>
                        )}

                        <button
                            type="submit"
                            disabled={loading}
                            className="w-full py-3 bg-accent-blue text-white border-none rounded-md text-sm font-semibold cursor-pointer transition-all duration-150 hover:bg-blue-600 hover:shadow-md disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            {loading ? 'Verifying...' : 'Verify Token'}
                        </button>
                    </form>

                    <div className="mt-6 text-center">
                        <button
                            onClick={() => { window.location.href = '/login'; }}
                            className="text-xs text-text-muted hover:text-text transition-all"
                        >
                            Back to Login
                        </button>
                    </div>
                </div>
            </div>
        );
    }

    if (otpStep && !registrationStep) {
        return (
            <div className="h-screen flex items-center justify-center bg-bg relative overflow-hidden">
                <button
                    onClick={toggleTheme}
                    className="absolute top-6 right-6 p-3 rounded-2xl bg-surface border border-border-subtle text-text-muted hover:bg-hover hover:text-text transition-all duration-150 z-20"
                    title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
                >
                    {theme === 'dark' ? <FontAwesomeIcon icon={faSun} /> : <FontAwesomeIcon icon={faMoon} />}
                </button>

                <div className="w-[400px] p-8 bg-surface border border-border-subtle rounded-xl shadow-lg relative z-10">
                    <div className="text-center mb-6">
                        <div className="w-full h-[80px] overflow-hidden rounded-xl mb-4">
                            <img src="/logo.png" alt="CorpOD" className="w-full h-full object-cover" />
                        </div>
                        <h2 className="text-xl font-semibold">Verify Your Email</h2>
                        {inviteData && (
                            <p className="text-success text-xs mt-2 font-medium">OTP sent to {maskEmail(inviteData.email)}</p>
                        )}
                    </div>

                    <form onSubmit={handleVerifyOtp}>
                        <div className="mb-5">
                            <label className="block text-xs text-text-muted mb-1.5 font-medium">One-Time Password</label>
                            <input
                                type="text"
                                maxLength={6}
                                className="w-full bg-elevated border border-border rounded-md px-3.5 py-3 text-sm text-text outline-none transition-all duration-200 focus:border-accent-blue focus:shadow-[0_0_0_3px_var(--color-accent-blue-muted)] font-mono text-center text-lg tracking-widest"
                                value={otp}
                                onChange={(e) => setOtp(e.target.value.replace(/\D/g, ''))}
                                placeholder="000000"
                                required
                            />
                        </div>

                        {error && (
                            <div className="text-error text-sm text-center mb-4 px-3 py-2.5 bg-error/10 border border-error/20 rounded-md">
                                {error}
                            </div>
                        )}

                        <button
                            type="submit"
                            disabled={loading}
                            className="w-full py-3 bg-accent-blue text-white border-none rounded-md text-sm font-semibold cursor-pointer transition-all duration-150 hover:bg-blue-600 hover:shadow-md disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            {loading ? 'Verifying...' : 'Verify OTP'}
                        </button>
                    </form>

                    <div className="mt-6 text-center">
                        <button
                            onClick={handleRequestOtp}
                            className="text-xs text-text-muted hover:text-text transition-all"
                        >
                            Resend OTP
                        </button>
                    </div>
                </div>
            </div>
        );
    }

    if (registrationStep) {
        return (
            <div className="h-screen flex items-center justify-center bg-bg relative overflow-hidden">
                <button
                    onClick={toggleTheme}
                    className="absolute top-6 right-6 p-3 rounded-2xl bg-surface border border-border-subtle text-text-muted hover:bg-hover hover:text-text transition-all duration-150 z-20"
                    title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
                >
                    {theme === 'dark' ? <FontAwesomeIcon icon={faSun} /> : <FontAwesomeIcon icon={faMoon} />}
                </button>

                <div className="w-[450px] p-8 bg-surface border border-border-subtle rounded-xl shadow-lg relative z-10">
                    <div className="text-center mb-6">
                        <div className="w-full h-[80px] overflow-hidden rounded-xl mb-4">
                            <img src="/logo.png" alt="CorpOD" className="w-full h-full object-cover" />
                        </div>
                        <h2 className="text-xl font-semibold">Complete Your Profile</h2>
                        <p className="text-xs text-text-muted mt-1">Role: {inviteData?.role} | Dept: {inviteData?.department}</p>
                    </div>

                    <form onSubmit={handleRegistration} className="flex flex-col gap-4">
                        <div>
                            <label className="block text-xs text-text-muted mb-1.5 font-medium">Username <span className="text-error">*</span></label>
                            <input
                                required
                                value={registrationData.username}
                                onChange={(e) => setRegistrationData({ ...registrationData, username: e.target.value })}
                                className="w-full bg-elevated border border-border rounded-md px-3.5 py-2.5 text-sm text-text outline-none focus:border-accent-blue focus:shadow-[0_0_0_3px_var(--color-accent-blue-muted)]"
                                placeholder="Choose a username"
                            />
                        </div>

                        <div>
                            <label className="block text-xs text-text-muted mb-1.5 font-medium">Full Name <span className="text-error">*</span></label>
                            <input
                                required
                                value={registrationData.full_name}
                                onChange={(e) => setRegistrationData({ ...registrationData, full_name: e.target.value })}
                                className="w-full bg-elevated border border-border rounded-md px-3.5 py-2.5 text-sm text-text outline-none focus:border-accent-blue focus:shadow-[0_0_0_3px_var(--color-accent-blue-muted)]"
                                placeholder="Your full name"
                            />
                        </div>

                        <div className="grid grid-cols-2 gap-4">
                            <div>
                                <label className="block text-xs text-text-muted mb-1.5 font-medium">Password <span className="text-error">*</span></label>
                                <input
                                    type="password"
                                    required
                                    value={registrationData.password}
                                    onChange={(e) => setRegistrationData({ ...registrationData, password: e.target.value })}
                                    className="w-full bg-elevated border border-border rounded-md px-3.5 py-2.5 text-sm text-text outline-none focus:border-accent-blue focus:shadow-[0_0_0_3px_var(--color-accent-blue-muted)]"
                                />
                            </div>
                            <div>
                                <label className="block text-xs text-text-muted mb-1.5 font-medium">Confirm Password <span className="text-error">*</span></label>
                                <input
                                    type="password"
                                    required
                                    value={registrationData.confirmPassword}
                                    onChange={(e) => setRegistrationData({ ...registrationData, confirmPassword: e.target.value })}
                                    className="w-full bg-elevated border border-border rounded-md px-3.5 py-2.5 text-sm text-text outline-none focus:border-accent-blue focus:shadow-[0_0_0_3px_var(--color-accent-blue-muted)]"
                                />
                            </div>
                        </div>

                        {error && (
                            <div className="text-error text-sm px-3 py-2.5 bg-error/10 border border-error/20 rounded-md">
                                {error}
                            </div>
                        )}

                        <button
                            type="submit"
                            disabled={loading}
                            className="mt-2 py-3 bg-accent-blue text-white rounded-lg text-sm font-semibold hover:bg-blue-600 disabled:opacity-50 transition-all flex items-center justify-center gap-2"
                        >
                            {loading ? 'Registering...' : <><FontAwesomeIcon icon={faRocket} /> Complete Registration</>}
                        </button>
                    </form>
                </div>
            </div>
        );
    }

    return (
        <div className="h-screen flex items-center justify-center bg-bg relative overflow-hidden">
            <button
                onClick={toggleTheme}
                className="absolute top-6 right-6 p-3 rounded-2xl bg-surface border border-border-subtle text-text-muted hover:bg-hover hover:text-text transition-all duration-150 z-20"
                title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            >
                {theme === 'dark' ? <FontAwesomeIcon icon={faSun} /> : <FontAwesomeIcon icon={faMoon} />}
            </button>

            <div className="absolute inset-0 pointer-events-none" style={{
                background: 'radial-gradient(ellipse at 30% 20%, rgba(59, 130, 246, 0.06) 0%, transparent 50%), radial-gradient(ellipse at 70% 80%, rgba(99, 102, 241, 0.04) 0%, transparent 50%)'
            }} />

            <div className="w-[400px] p-8 bg-surface border border-border-subtle rounded-xl shadow-lg relative z-10">
                <div className="text-center mb-8">
                    <div className="w-full h-[120px] overflow-hidden rounded-xl">
                        <img src="/logo.png" alt="CorpOD" className="w-full h-full object-cover" />
                    </div>
                    <p className="text-sm text-text-muted mt-1">Identity & Access Management</p>
                </div>

                <form onSubmit={handleSubmit}>
                    <div className="mb-5">
                        <label className="block text-xs text-text-muted mb-1.5 font-medium">Username or Email</label>
                        <input
                            id="login-username"
                            type="text"
                            className="w-full bg-elevated border border-border rounded-md px-3.5 py-3 text-sm text-text outline-none transition-all duration-200 focus:border-accent-blue focus:shadow-[0_0_0_3px_var(--color-accent-blue-muted)] placeholder:text-text-muted"
                            value={username}
                            onChange={(e) => setUsername(e.target.value)}
                            placeholder="e.g. rookie, admin"
                            required
                        />
                    </div>
                    <div className="mb-5">
                        <label className="block text-xs text-text-muted mb-1.5 font-medium">Password</label>
                        <input
                            id="login-password"
                            type="password"
                            className="w-full bg-elevated border border-border rounded-md px-3.5 py-3 text-sm text-text outline-none transition-all duration-200 focus:border-accent-blue focus:shadow-[0_0_0_3px_var(--color-accent-blue-muted)] placeholder:text-text-muted"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            placeholder="••••••••"
                            required
                        />
                    </div>

                    {error && (
                        <div className="text-error text-sm text-center mb-4 px-3 py-2.5 bg-error/10 border border-error/20 rounded-md">
                            {error}
                        </div>
                    )}

                    <button
                        id="login-submit"
                        type="submit"
                        className="w-full py-3 bg-accent-blue text-white border-none rounded-md text-sm font-semibold cursor-pointer transition-all duration-150 hover:bg-blue-600 hover:shadow-md disabled:opacity-50 disabled:cursor-not-allowed"
                        disabled={loading}
                    >
                        {loading ? 'Authenticating...' : 'Sign In'}
                    </button>

                    <div className="mt-6 text-center">
                        <p className="text-xs text-text-muted mb-3">Are you a new employee?</p>
                        <button
                            type="button"
                            onClick={() => onLogin(null, null, true)}
                            className="w-full py-3 bg-transparent border border-border text-text-secondary rounded-md text-sm font-medium cursor-pointer transition-all duration-150 hover:bg-hover hover:border-white/20 hover:text-text"
                        >
                            <FontAwesomeIcon icon={faRocket} className="mr-2" /> Register as New Employee
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
};

export default LoginPage;