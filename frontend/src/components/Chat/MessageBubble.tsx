import React from 'react';
import { Message, ToolActivity } from '../../types';
import './MessageBubble.css';

interface Props { message: Message }

const TOOL_LABELS: Record<string, string> = {
    search_flights: '✈️ Amadeus Flights',
    search_airport_by_city: '🗺️ Airport Lookup',
    search_aircraft_by_callsign: '📡 ADSBDB Callsign',
    search_aircraft_by_registration: '📡 ADSBDB Aircraft',
    create_trip_document: '📄 Google Docs',
    create_calendar_event: '📅 Google Calendar',
};

function ToolBadge({ activity }: { activity: ToolActivity }) {
    const label = TOOL_LABELS[activity.tool] ?? activity.tool;
    const statusClass =
        activity.status === 'success' ? 'badge--success' :
            activity.status === 'error' ? 'badge--error' : 'badge--running';

    return (
        <span className={`tool-badge ${statusClass}`}>
            {activity.status === 'running' && <span className="tool-badge__spinner" />}
            {activity.status === 'success' && '✓ '}
            {activity.status === 'error' && '✗ '}
            {label}
        </span>
    );
}

export function MessageBubble({ message }: Props) {
    const isUser = message.role === 'user';
    const hasTools = (message.toolActivity?.length ?? 0) > 0;

    return (
        <div className={`bubble-wrapper ${isUser ? 'bubble-wrapper--user' : 'bubble-wrapper--assistant'}`}>
            {!isUser && (
                <div className="bubble-avatar">
                    <span>🌍</span>
                </div>
            )}
            <div className={`bubble ${isUser ? 'bubble--user' : 'bubble--assistant'}`}>
                {hasTools && (
                    <div className="bubble__tools">
                        {message.toolActivity!.map((a, i) => (
                            <ToolBadge key={`${a.tool}-${i}`} activity={a} />
                        ))}
                    </div>
                )}

                <div
                    className="bubble__content"
                    dangerouslySetInnerHTML={{ __html: renderMarkdown(message.content) }}
                />

                {message.isStreaming && (
                    <span className="bubble__cursor">▋</span>
                )}
            </div>
        </div>
    );
}

/**
 * Minimal markdown renderer (bold, italic, links, code, line breaks).
 * In production you'd use react-markdown, but keeping it dependency-light.
 */
function renderMarkdown(text: string): string {
    return text
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        .replace(/_(.+?)_/g, '<em>$1</em>')
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        .replace(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>')
        .replace(/\n/g, '<br/>');
}
