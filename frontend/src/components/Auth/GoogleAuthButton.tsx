import { useState, useEffect, useCallback } from 'react';
import './GoogleAuthButton.css';

interface Props {
    sessionId: string | null;
    onTokenReceived: (token: Record<string, string>) => void;
}

const API_BASE = 'http://localhost:8001';

export function GoogleAuthButton({ sessionId, onTokenReceived }: Props) {
    const [status, setStatus] = useState<'idle' | 'pending' | 'success'>('idle');

    // Listen for postMessage from the OAuth popup
    useEffect(() => {
        function handleMessage(event: MessageEvent) {
            const data = event.data;
            if (!data || typeof data !== 'object') return;

            if (data.type === 'navigo-auth-success') {
                onTokenReceived(data.token);
                setStatus('success');
            } else if (data.type === 'navigo-auth-error') {
                console.error('Google auth error:', data.message);
                setStatus('idle');
            }
        }

        window.addEventListener('message', handleMessage);
        return () => window.removeEventListener('message', handleMessage);
    }, [onTokenReceived]);

    const handleAuth = useCallback(async () => {
        if (!sessionId) return;
        setStatus('pending');

        try {
            const res = await fetch(`${API_BASE}/api/auth/google?session_id=${sessionId}`);
            const { auth_url } = await res.json();

            // Open Google consent in a popup — the callback page will postMessage back
            const popup = window.open(
                auth_url,
                'Google Auth',
                'width=520,height=640,scrollbars=yes,resizable=yes'
            );

            // Fallback: if popup is closed without posting (user dismissed), reset
            const pollClosed = setInterval(() => {
                if (popup?.closed) {
                    clearInterval(pollClosed);
                    setStatus(s => s === 'pending' ? 'idle' : s);
                }
            }, 500);

        } catch {
            setStatus('idle');
        }
    }, [sessionId]);

    if (status === 'success') {
        return (
            <div className="auth-badge auth-badge--success">
                <span>✓</span> Google Connected
            </div>
        );
    }

    return (
        <button
            className="auth-btn"
            onClick={handleAuth}
            disabled={!sessionId || status === 'pending'}
        >
            {status === 'pending' ? (
                <><span className="auth-btn__spinner" /> Connecting…</>
            ) : (
                <>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4" />
                        <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
                        <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05" />
                        <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335" />
                    </svg>
                    Connect Google
                </>
            )}
        </button>
    );
}
