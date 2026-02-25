import React, { useState, useRef, useEffect, useCallback } from 'react';
import './App.css';
import { Message } from './types';
import { useAgent } from './hooks/useAgent';
import { MessageBubble } from './components/Chat/MessageBubble';
import { ChatInput } from './components/Chat/ChatInput';
import { GoogleAuthButton } from './components/Auth/GoogleAuthButton';

const WELCOME: Message = {
  id: 'welcome',
  role: 'assistant',
  content: "✈️ **Welcome to NaviGO!** I'm your AI travel companion powered by Llama 4.\n\nTell me about your dream trip and I'll search real flights, enrich them with live aircraft data, and—with your permission—create a Google Docs itinerary and add it to your calendar.\n\n*Where would you like to go?*",
  timestamp: new Date(),
};

export default function App() {
  const [messages, setMessages] = useState<Message[]>([WELCOME]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const { sendMessage, setGoogleToken } = useAgent({
    onMessageUpdate: setMessages,
    onSessionId: setSessionId,
  });

  // Scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = useCallback(async (text: string) => {
    setIsLoading(true);
    await sendMessage(text);
    setIsLoading(false);
  }, [sendMessage]);

  const handleTokenReceived = useCallback((token: Record<string, string>) => {
    setGoogleToken(token);
  }, [setGoogleToken]);

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
            Llama 4 Maverick · Groq
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
          {sessionId && (
            <span className="chat-header__session" title={sessionId}>
              Session active
            </span>
          )}
        </header>

        <div className="chat-messages" role="log" aria-live="polite">
          {messages.map(msg => (
            <MessageBubble key={msg.id} message={msg} />
          ))}
          <div ref={messagesEndRef} />
        </div>

        <ChatInput onSend={handleSend} disabled={isLoading} />
      </main>
    </div>
  );
}
