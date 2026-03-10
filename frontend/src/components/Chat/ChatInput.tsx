import React, { useState, useCallback, useMemo } from 'react';
import './ChatInput.css';

interface Props {
    onSend: (msg: string) => void;
    onStop?: () => void;
    disabled?: boolean;
    isStreaming?: boolean;
    lastAssistantMessage?: string;
}

// ── Dynamic suggestion engine ──────────────────────────────────────────────
// Matches the agent's last message to contextually relevant quick-reply chips.
function getSuggestions(msg: string): string[] {

    // Confirmation prompts — only match when agent is *explicitly asking* the user
    // (requires question phrasing). Avoids false positives on the welcome message
    // which mentions 'create' and 'calendar' as passive capability descriptions.
    if (/(shall i|should i|would you like me to|want me to|ready to).*(doc|document|itinerary|calendar|event)/i.test(msg)
        || /(confirm|go ahead|proceed).*(creat|generat|add)/i.test(msg)) {
        return ['Yes, create both!', 'Yes, document only', 'Yes, calendar only', 'No thanks'];
    }

    // Passenger / traveler count
    if (/(how many|number of|passenger|travell?er|adult|people|who.*(travel|fly))/i.test(msg)) {
        return ['Just me (1 adult)', '2 adults', '2 adults + 1 child', 'Family of 4'];
    }

    // Travel dates / timing
    if (/(when|date|depart|return|how long|duration|week|month)/i.test(msg)) {
        return ['This weekend', 'Next month', 'In 3 months', 'December'];
    }

    // Budget / class preference
    if (/(budget|class|comfort|prefer|economy|business|price)/i.test(msg)) {
        return ['Economy, cheapest', 'Economy, best value', 'Business class', 'No preference'];
    }

    // Origin / departure airport
    if (/(from|origin|depart|flying from|where are you|start)/i.test(msg)) {
        return ['Tel Aviv (TLV)', 'London (LHR)', 'New York (JFK)', 'Paris (CDG)'];
    }

    // Destination
    if (/(where|destination|go|visit|travel to|trip to|fly to)/i.test(msg)) {
        return ['Barcelona 🇪🇸', 'Tokyo 🇯🇵', 'New York 🇺🇸', 'Paris 🇫🇷'];
    }

    // Self-correction / retry prompts
    if (/(error|fail|couldn't|sorry|try again|alternative)/i.test(msg)) {
        return ['Try again', 'Search different dates', 'Change destination', 'Start over'];
    }

    // Default welcome / opening suggestions
    return [
        'Plan a trip from Tel Aviv to Barcelona',
        'Find flights to Tokyo for 2 adults',
        'I want to visit Paris next month',
    ];
}

export function ChatInput({ onSend, onStop, disabled, isStreaming, lastAssistantMessage }: Props) {
    const [value, setValue] = useState('');

    const suggestions = useMemo(
        () => getSuggestions(lastAssistantMessage ?? ''),
        [lastAssistantMessage]
    );

    const handleSend = useCallback((text: string) => {
        const trimmed = text.trim();
        if (!trimmed || (disabled && !isStreaming)) return;
        onSend(trimmed);
        setValue('');
    }, [onSend, disabled, isStreaming]);

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSend(value);
        }
    };

    return (
        <div className="chat-input-area">
            {!isStreaming && (
                <div className="chat-input-suggestions">
                    {suggestions.map(s => (
                        <button
                            key={s}
                            className="suggestion-chip"
                            onClick={() => handleSend(s)}
                            disabled={disabled}
                        >
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
                    disabled={disabled && !isStreaming}
                />
                {isStreaming ? (
                    <button
                        className="chat-input__stop"
                        onClick={onStop}
                        aria-label="Stop generation"
                        title="Stop generation"
                    >
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
                            <rect x="4" y="4" width="16" height="16" rx="2" />
                        </svg>
                    </button>
                ) : (
                    <button
                        className="chat-input__send"
                        onClick={() => handleSend(value)}
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
                )}
            </div>
        </div>
    );
}
