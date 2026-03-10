import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import './App.css';
import type { Message } from './types';
import { useAgent } from './hooks/useAgent';
import { MessageBubble } from './components/Chat/MessageBubble';
import { ChatInput } from './components/Chat/ChatInput';
import { GoogleAuthButton } from './components/Auth/GoogleAuthButton';

const API = 'http://localhost:8001';

const WELCOME: Message = {
  id: 'welcome',
  role: 'assistant',
  content: "✈️ **Welcome to NaviGO!** I'm your AI travel companion powered by qwen3-32b.\n\nTell me about your dream trip and I'll search real flights, enrich them with live aircraft data, and—with your permission—create a Google Docs itinerary and add it to your calendar.\n\n*Where would you like to go?*",
  timestamp: new Date(),
};

export default function App() {
  const [messages, setMessages] = useState<Message[]>([WELCOME]);
  const [sessionId, setSessionId] = useState<string>(() => crypto.randomUUID());
  const [sessions, setSessions] = useState<{ id: string, title: string, updated_at: string }[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [googleToken, setGoogleToken] = useState<Record<string, string> | null>(null);
  // Theme: 'dark' (default) or 'light'
  const [theme, setTheme] = useState<'dark' | 'light'>('dark');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Apply theme to document root
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  const toggleTheme = useCallback(() => {
    setTheme(t => t === 'dark' ? 'light' : 'dark');
  }, []);

  // Load past sessions
  const fetchSessions = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/chat/sessions`);
      if (res.ok) {
        const data = await res.json();
        setSessions(data.sessions || []);
      }
    } catch (err) {
      console.error('Failed to fetch sessions:', err);
    }
  }, []);

  useEffect(() => {
    fetchSessions();
  }, [messages, fetchSessions]);

  const loadSession = useCallback(async (id: string) => {
    try {
      const res = await fetch(`${API}/api/chat/session/${id}/history`);
      if (res.ok) {
        const data = await res.json();
        const loaded = data.history.map((msg: any) => ({
          id: crypto.randomUUID(),
          role: msg.role,
          content: msg.content,
          timestamp: new Date(),
        }));
        setSessionId(id);
        setMessages(loaded.length ? loaded : [WELCOME]);
      }
    } catch (err) {
      console.error('Failed to load session history:', err);
    }
  }, []);

  const deleteSession = useCallback(async (e: React.MouseEvent, id: string) => {
    e.stopPropagation(); // Don't trigger loadSession
    try {
      await fetch(`${API}/api/chat/session/${id}`, { method: 'DELETE' });
      setSessions(prev => prev.filter(s => s.id !== id));
      // If we deleted the active session, start a new one
      if (id === sessionId) {
        setSessionId(crypto.randomUUID());
        setMessages([WELCOME]);
      }
    } catch (err) {
      console.error('Failed to delete session:', err);
    }
  }, [sessionId]);

  const handleNewChat = useCallback(() => {
    setSessionId(crypto.randomUUID());
    setMessages([WELCOME]);
  }, []);

  const { sendMessage, stopGeneration } = useAgent({
    onMessageUpdate: setMessages,
    onSessionId: setSessionId,
    initialSessionId: sessionId,
    googleToken,
  });

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = useCallback(async (text: string) => {
    setIsLoading(true);
    setIsStreaming(true);
    await sendMessage(text);
    setIsLoading(false);
    setIsStreaming(false);
  }, [sendMessage]);

  // Last assistant message text — drives dynamic suggestion chips
  const lastAssistantMessage = useMemo(() => {
    const assistantMsgs = messages.filter(m => m.role === 'assistant');
    return assistantMsgs.at(-1)?.content ?? '';
  }, [messages]);

  const handleStop = useCallback(() => {
    stopGeneration();
    setIsLoading(false);
    setIsStreaming(false);
  }, [stopGeneration]);

  const handleTokenReceived = useCallback((token: Record<string, string>) => {
    setGoogleToken(token);
  }, []);

  return (
    <div className="app-layout">
      {/* ── Sidebar ─────────────────────────────────────────────────── */}
      <aside className="sidebar glass">
        <div className="sidebar__logo">
          <span className="sidebar__logo-icon">🌍</span>
          <span className="sidebar__logo-text">NaviGO</span>
          <span className="sidebar__logo-badge">AI</span>
        </div>

        <div className="sidebar__section">
          <p className="sidebar__label">Powered by</p>
          <div className="sidebar__model-chip">
            <span className="sidebar__model-dot" />
            qwen3-32b 70B · Groq
          </div>
        </div>

        <div className="sidebar__section">
          <p className="sidebar__label">Google Workspace</p>
          <GoogleAuthButton
            sessionId={sessionId}
            onTokenReceived={handleTokenReceived}
          />
          <p className="sidebar__hint">
            Grant access to let NaviGO create your trip doc and calendar event.
          </p>
        </div>

        <div className="sidebar__section sidebar__history">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <p className="sidebar__label" style={{ margin: 0 }}>Recent Trips</p>
            <button
              onClick={handleNewChat}
              style={{ background: 'none', border: 'none', color: 'var(--accent-teal)', cursor: 'pointer', fontSize: '1.3rem', lineHeight: 1 }}
              title="New Chat"
            >
              +
            </button>
          </div>
          <ul className="sidebar__cap-list" style={{ maxHeight: '180px', overflowY: 'auto' }}>
            {sessions.map(s => (
              <li
                key={s.id}
                className="sidebar__cap-item"
                style={{
                  cursor: 'pointer',
                  background: s.id === sessionId ? 'rgba(0,212,170,0.08)' : 'transparent',
                  padding: '6px 4px',
                  borderRadius: '6px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: '6px',
                }}
                onClick={() => loadSession(s.id)}
              >
                <span style={{ display: 'flex', gap: '6px', alignItems: 'center', overflow: 'hidden' }}>
                  <span>💬</span>
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {s.title || 'Untitled Trip'}
                  </span>
                </span>
                <button
                  onClick={(e) => deleteSession(e, s.id)}
                  title="Delete session"
                  style={{
                    background: 'none', border: 'none', cursor: 'pointer',
                    color: 'var(--text-muted)', fontSize: '14px', flexShrink: 0,
                    padding: '2px 4px', borderRadius: '4px', lineHeight: 1,
                    opacity: 0.6, transition: 'opacity 0.2s, color 0.2s',
                  }}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.opacity = '1'; (e.currentTarget as HTMLElement).style.color = 'var(--error, #ef4444)'; }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.opacity = '0.6'; (e.currentTarget as HTMLElement).style.color = 'var(--text-muted)'; }}
                >
                  ✕
                </button>
              </li>
            ))}
            {sessions.length === 0 && <li className="sidebar__cap-item" style={{ opacity: 0.5 }}>No recent trips</li>}
          </ul>
        </div>

        <div className="sidebar__section sidebar__capabilities">
          <p className="sidebar__label">Capabilities</p>
          <ul className="sidebar__cap-list">
            {[
              { icon: '✈️', label: 'Real flight search (Amadeus)' },
              { icon: '📡', label: 'Live aircraft data (ADSBDB)' },
              { icon: '📄', label: 'Google Docs itinerary' },
              { icon: '📅', label: 'Google Calendar event' },
              { icon: '🔄', label: 'Self-correcting ReAct AI' },
              { icon: '🧠', label: 'Remembers your preferences' },
            ].map(({ icon, label }) => (
              <li key={label} className="sidebar__cap-item">
                <span>{icon}</span> {label}
              </li>
            ))}
          </ul>
        </div>

        <div className="sidebar__footer">
          NaviGO · NAVAN Challenge 2026
        </div>
      </aside>

      {/* ── Main Chat ───────────────────────────────────────────────── */}
      <main className="chat-main">
        <header className="chat-header glass">
          <div className="chat-header__info">
            <span className="chat-header__title">AI Travel Agent</span>
            <span className="chat-header__status">
              <span className="chat-header__dot" />
              Online · ReAct Mode
            </span>
          </div>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            {/* Theme toggle */}
            <button
              onClick={toggleTheme}
              title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
              style={{
                background: 'var(--bg-elevated)', border: '1px solid var(--border)',
                borderRadius: '8px', padding: '6px 10px', cursor: 'pointer',
                color: 'var(--text-secondary)', fontSize: '16px', lineHeight: 1,
                transition: 'background 0.2s',
              }}
            >
              {theme === 'dark' ? '☀️' : '🌙'}
            </button>
            <span className="chat-header__session" title={sessionId}>
              Session active
            </span>
          </div>
        </header>

        <div className="chat-messages" role="log" aria-live="polite">
          {messages.map(msg => (
            <MessageBubble key={msg.id} message={msg} />
          ))}
          <div ref={messagesEndRef} />
        </div>

        <ChatInput
          onSend={handleSend}
          onStop={handleStop}
          disabled={isLoading}
          isStreaming={isStreaming}
          lastAssistantMessage={lastAssistantMessage}
        />
      </main>
    </div>
  );
}
