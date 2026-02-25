import React, { useState, useCallback } from 'react';
import './ChatInput.css';

interface Props {
    onSend: (msg: string) => void;
    disabled?: boolean;
}

export function ChatInput({ onSend, disabled }: Props) {
    const [value, setValue] = useState('');

    const handleSend = useCallback(() => {
        const trimmed = value.trim();
        if (!trimmed || disabled) return;
        onSend(trimmed);
        setValue('');
    }, [value, onSend, disabled]);

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    };

    const suggestions = [
        "Plan a trip from Tel Aviv to Barcelona",
        "Find flights to Tokyo for 2 adults",
        "I want to visit Paris next month",
    ];

    return (
        <div className="chat-input-area">
            {!disabled && (
                <div className="chat-input-suggestions">
                    {suggestions.map(s => (
                        <button key={s} className="suggestion-chip" onClick={() => onSend(s)}>
                            {s}
                        </button>
                    ))}
                </div>
            )}
            <div className="chat-input-row">
                <textarea
                    className="chat-input__field"
                    value={value}
                    onChange={e => setValue(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder="Tell me about your dream trip..."
                    rows={1}
                    disabled={disabled}
                />
                <button
                    className="chat-input__send"
                    onClick={handleSend}
                    disabled={disabled || !value.trim()}
                    aria-label="Send message"
                >
                    {disabled ? (
                        <span className="send-spinner" />
                    ) : (
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                            <path d="M22 2L11 13" /><path d="M22 2L15 22l-4-9-9-4 20-7z" />
                        </svg>
                    )}
                </button>
            </div>
        </div>
    );
}
