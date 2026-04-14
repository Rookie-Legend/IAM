import React, { useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faRocket, faEnvelope, faCheck } from '@fortawesome/free-solid-svg-icons';
import { apiUrl } from '../stores/configStore';

const maskEmail = (email) => {
    if (!email) return '';
    const [user, domain] = email.split('@');
    if (!domain) return email;
    const maskedUser = user.length > 4 ? user.slice(0, 4) + '***' + user.slice(-2) : user.slice(0, 2) + '***';
    return `${maskedUser}@${domain}`;
};

export default function Joiner({ onBack }) {
  const [step, setStep] = useState('token'); // token | otp | registration | success
  const [token, setToken] = useState('');
  const [inviteData, setInviteData] = useState(null);
  const [otp, setOtp] = useState('');
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const [formData, setFormData] = useState({
    username: '',
    full_name: '',
    password: '',
    confirmPassword: ''
  });

  const handleVerifyToken = async (e) => {
    e.preventDefault();
    setLoading(true);
    setErrorMsg('');
    try {
      const res = await fetch(apiUrl('/api/auth/verify-invite-token'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token })
      });
      const data = await res.json();
      if (!res.ok) {
        setErrorMsg(data.detail || 'Invalid or expired invite token');
        return;
      }
      setInviteData(data);

      const otpRes = await fetch(apiUrl('/api/auth/request-registration-otp'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token })
      });
      if (!otpRes.ok) {
        const otpData = await otpRes.json();
        setErrorMsg(otpData.detail || 'Failed to send OTP');
        return;
      }
      setStep('otp');
    } catch (err) {
      setErrorMsg('Could not connect to server');
    } finally {
      setLoading(false);
    }
  };

  const handleRequestOtp = async () => {
    setLoading(true);
    setErrorMsg('');
    try {
      const res = await fetch(apiUrl('/api/auth/request-registration-otp'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token })
      });
      const data = await res.json();
      if (!res.ok) {
        setErrorMsg(data.detail || 'Failed to send OTP');
        return;
      }
    } catch (err) {
      setErrorMsg('Could not connect to server');
    } finally {
      setLoading(false);
    }
  };

  const handleVerifyOtp = async (e) => {
    e.preventDefault();
    setLoading(true);
    setErrorMsg('');
    try {
      const res = await fetch(apiUrl('/api/auth/verify-registration-otp'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, otp })
      });
      const data = await res.json();
      if (!res.ok) {
        setErrorMsg(data.detail || 'Invalid or expired OTP');
        return;
      }
      setStep('registration');
    } catch (err) {
      setErrorMsg('Could not connect to server');
    } finally {
      setLoading(false);
    }
  };

  const handleRegistration = async (e) => {
    e.preventDefault();
    if (formData.password !== formData.confirmPassword) {
      setErrorMsg('Passwords do not match');
      return;
    }
    setLoading(true);
    setErrorMsg('');
    try {
      const res = await fetch(apiUrl('/api/auth/complete-registration'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          token,
          username: formData.username,
          full_name: formData.full_name,
          password: formData.password
        })
      });
      const data = await res.json();
      if (!res.ok) {
        setErrorMsg(data.detail || 'Registration failed');
        return;
      }
      setStep('success');
    } catch (err) {
      setErrorMsg('Could not connect to server');
    } finally {
      setLoading(false);
    }
  };

  if (step === 'success') {
    return (
      <div className="h-screen flex flex-col items-center justify-center bg-bg text-text">
        <div className="w-full max-w-md bg-surface border border-border-subtle rounded-2xl shadow-2xl p-10 text-center">
          <div className="text-5xl mb-5 flex justify-center"><FontAwesomeIcon icon={faCheck} className="text-success" /></div>
          <h2 className="text-2xl font-bold mb-3">Registration Complete!</h2>
          <p className="text-text-muted mb-6">Your account has been created. You can now login with your credentials.</p>
          <button onClick={onBack} className="w-full py-3 bg-accent-blue text-white rounded-lg text-sm font-semibold hover:bg-blue-600 transition-all">
            Back to Login
          </button>
        </div>
      </div>
    );
  }

  if (step === 'otp') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-bg text-text py-10">
        <div className="w-full max-w-md bg-surface border border-border-subtle rounded-2xl overflow-hidden" style={{ maxWidth: '400px', boxShadow: 'var(--color-shadow-strong)' }}>
          <div className="p-8">
            <div className="text-center mb-6">
              <div className="flex justify-center mb-4">
                <img src="/logo.png" alt="CorpOD Logo" className="h-12" />
              </div>
              <h2 className="text-2xl font-bold text-text">CorpOD Security</h2>
            </div>

            <p className="text-text-muted text-center mb-8">
              Enter the 6-digit code sent to your email
            </p>

            <form onSubmit={handleVerifyOtp} className="flex flex-col gap-6">
              <div className="flex justify-center items-center gap-2">
                {[...Array(6)].map((_, i) => (
                  <input
                    key={i}
                    id={`otp-${i}`}
                    type="text"
                    inputMode="numeric"
                    maxLength={1}
                    value={otp[i] || ''}
                    onChange={(e) => {
                      const val = e.target.value.replace(/\D/g, '');
                      const newOtp = otp.split('');
                      if (val) {
                        newOtp[i] = val.slice(-1);
                        setOtp(newOtp.join('').slice(0, 6));
                        if (i < 5) document.getElementById(`otp-${i + 1}`)?.focus();
                      } else {
                        newOtp[i] = '';
                        setOtp(newOtp.join(''));
                      }
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Backspace' && !otp[i] && i > 0) {
                        const newOtp = otp.split('');
                        newOtp[i-1] = '';
                        setOtp(newOtp.join(''));
                        document.getElementById(`otp-${i - 1}`)?.focus();
                      }
                    }}
                    className="w-11 h-13 bg-elevated border border-border rounded-lg text-center text-2xl font-bold text-text outline-none focus:border-accent-blue focus:ring-1 transition-all shadow-sm"
                    style={{ boxShadow: '0 1px 2px var(--color-border)', '--tw-ring-color': 'var(--color-accent-blue-muted)' }}
                    required
                  />
                ))}
              </div>

              {errorMsg && (
                <div className="text-error text-sm px-4 py-3 bg-error/10 border border-error/20 rounded-lg text-center">
                  {errorMsg}
                </div>
              )}

              <button
                type="submit"
                disabled={loading || otp.length < 6}
                className="w-full py-3 bg-accent-blue text-white rounded-lg text-sm font-semibold hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
              >
                {loading ? 'Verifying...' : 'Verify Code'}
              </button>
            </form>

            <div className="mt-6 text-center border-t border-border-subtle pt-4">
              <p className="text-xs text-text-muted mb-2">This code expires in 5 minutes.</p>
              <p className="text-xs text-text-muted/70">
                If you didn't request this, you can safely ignore this email.
              </p>
            </div>

            <div className="mt-4 text-center">
              <p className="text-xs text-text-muted">
                Didn't receive the code?{' '}
                <button
                  type="button"
                  onClick={handleRequestOtp}
                  disabled={loading}
                  className="text-accent-blue font-semibold hover:underline"
                >
                  Resend OTP
                </button>
              </p>
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (step === 'registration') {
    return (
      <div className="h-screen flex flex-col items-center justify-center bg-bg text-text overflow-y-auto py-8">
        <div className="w-full max-w-lg bg-surface border border-border-subtle rounded-2xl shadow-2xl overflow-hidden">
          <div className="px-8 py-6 border-b border-border-subtle flex items-center gap-4 bg-accent-blue/5">
            <FontAwesomeIcon icon={faRocket} className="text-2xl text-accent-blue" />
            <div>
              <h2 className="text-lg font-semibold">Complete Your Profile</h2>
              <p className="text-xs text-text-muted">Role: {inviteData?.role} | Dept: {inviteData?.department}</p>
            </div>
            <button onClick={onBack} className="ml-auto px-3 py-1.5 border border-border text-text-secondary text-xs rounded-lg hover:bg-hover transition-all">
              Cancel
            </button>
          </div>

          <form onSubmit={handleRegistration} className="p-8 flex flex-col gap-4">
            <div>
              <label className="block text-xs text-text-muted mb-1.5 font-medium">Username <span className="text-error">*</span></label>
              <input
                required
                value={formData.username}
                onChange={(e) => setFormData({ ...formData, username: e.target.value })}
                className="w-full bg-elevated border border-border rounded-md px-3.5 py-2.5 text-sm text-text outline-none focus:border-accent-blue focus:shadow-[0_0_0_3px_var(--color-accent-blue-muted)]"
                placeholder="Choose a username"
              />
            </div>

            <div>
              <label className="block text-xs text-text-muted mb-1.5 font-medium">Full Name <span className="text-error">*</span></label>
              <input
                required
                value={formData.full_name}
                onChange={(e) => setFormData({ ...formData, full_name: e.target.value })}
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
                  value={formData.password}
                  onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                  className="w-full bg-elevated border border-border rounded-md px-3.5 py-2.5 text-sm text-text outline-none focus:border-accent-blue focus:shadow-[0_0_0_3px_var(--color-accent-blue-muted)]"
                />
              </div>
              <div>
                <label className="block text-xs text-text-muted mb-1.5 font-medium">Confirm Password <span className="text-error">*</span></label>
                <input
                  type="password"
                  required
                  value={formData.confirmPassword}
                  onChange={(e) => setFormData({ ...formData, confirmPassword: e.target.value })}
                  className="w-full bg-elevated border border-border rounded-md px-3.5 py-2.5 text-sm text-text outline-none focus:border-accent-blue focus:shadow-[0_0_0_3px_var(--color-accent-blue-muted)]"
                />
              </div>
            </div>

            {errorMsg && (
              <div className="text-error text-sm px-3 py-2.5 bg-error/10 border border-error/20 rounded-md">{errorMsg}</div>
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
    <div className="h-screen flex flex-col items-center justify-center bg-bg text-text overflow-y-auto py-8">
      <div className="w-full max-w-md bg-surface border border-border-subtle rounded-2xl shadow-2xl overflow-hidden">
        <div className="px-8 py-6 border-b border-border-subtle flex items-center gap-4 bg-accent-blue/5">
          <FontAwesomeIcon icon={faRocket} className="text-2xl text-accent-blue" />
          <div>
            <h2 className="text-lg font-semibold">Join CorpOD</h2>
            <p className="text-xs text-text-muted">New Employee Registration</p>
          </div>
          <button onClick={onBack} className="ml-auto px-3 py-1.5 border border-border text-text-secondary text-xs rounded-lg hover:bg-hover transition-all">
            Cancel
          </button>
        </div>

        <div className="p-8">
          <p className="text-sm text-text-muted mb-4 text-center">
            Enter your invite token to begin the registration process.
          </p>

          <form onSubmit={handleVerifyToken} className="flex flex-col gap-4">
            <div>
              <label className="block text-xs text-text-muted mb-1.5 font-medium">Invite Token <span className="text-error">*</span></label>
              <input
                required
                value={token}
                onChange={(e) => setToken(e.target.value)}
                className="w-full bg-elevated border border-border rounded-md px-3.5 py-2.5 text-sm text-text outline-none focus:border-accent-blue focus:shadow-[0_0_0_3px_var(--color-accent-blue-muted)] font-mono"
                placeholder="Paste your invite token here"
              />
            </div>

            {errorMsg && (
              <div className="text-error text-sm px-3 py-2.5 bg-error/10 border border-error/20 rounded-md">{errorMsg}</div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="py-3 bg-accent-blue text-white rounded-lg text-sm font-semibold hover:bg-blue-600 disabled:opacity-50 transition-all flex items-center justify-center gap-2"
            >
              {loading ? 'Verifying...' : 'Verify Token & Send OTP'}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
