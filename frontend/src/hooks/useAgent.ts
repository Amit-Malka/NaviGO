import { useCallback, useRef } from 'react';
import type { Message, ToolActivity, TokenEvent, ToolStartEvent, ToolEndEvent, SelfCorrectionEvent, DoneEvent } from '../types';

const API_BASE = 'http://localhost:8001';

interface UseAgentOptions {
    onMessageUpdate: (updater: (msgs: Message[]) => Message[]) => void;
    onSessionId: (id: string) => void;
    initialSessionId?: string;
}

export function useAgent({ onMessageUpdate, onSessionId, initialSessionId }: UseAgentOptions) {
    const sessionIdRef = useRef<string>(initialSessionId ?? crypto.randomUUID());
    const googleTokenRef = useRef<Record<string, string> | null>(null);
    const abortRef = useRef<AbortController | null>(null);

    // Keep sessionIdRef in sync if initialSessionId changes (first render)
    if (initialSessionId && sessionIdRef.current !== initialSessionId) {
        sessionIdRef.current = initialSessionId;
    }

    const setGoogleToken = useCallback((token: Record<string, string>) => {
        googleTokenRef.current = token;
    }, []);

    const sendMessage = useCallback(async (userText: string) => {
        // Abort any active stream
        abortRef.current?.abort();
        abortRef.current = new AbortController();

        const userMsg: Message = {
            id: crypto.randomUUID(),
            role: 'user',
            content: userText,
            timestamp: new Date(),
        };

        const assistantMsgId = crypto.randomUUID();
        const assistantMsg: Message = {
            id: assistantMsgId,
            role: 'assistant',
            content: '',
            toolActivity: [],
            isStreaming: true,
            timestamp: new Date(),
        };

        onMessageUpdate(msgs => [...msgs, userMsg, assistantMsg]);

        try {
            const res = await fetch(`${API_BASE}/api/chat/stream`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: userText,
                    session_id: sessionIdRef.current,
                    google_token: googleTokenRef.current,
                }),
                signal: abortRef.current.signal,
            });

            if (!res.ok || !res.body) throw new Error(`API error: ${res.status}`);

            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() ?? '';

                let eventType = '';
                for (const line of lines) {
                    if (line.startsWith('event:')) {
                        eventType = line.slice(6).trim();
                    } else if (line.startsWith('data:')) {
                        const raw = line.slice(5).trim();
                        try {
                            const payload = JSON.parse(raw);
                            handleSseEvent(eventType, payload, assistantMsgId);
                        } catch { /* ignore parse errors */ }
                        eventType = '';
                    }
                }
            }
        } catch (err: unknown) {
            if (err instanceof Error && err.name !== 'AbortError') {
                onMessageUpdate(msgs =>
                    msgs.map(m => m.id === assistantMsgId
                        ? { ...m, content: m.content || 'An error occurred. Please try again.', isStreaming: false }
                        : m
                    )
                );
            }
        }
    }, [onMessageUpdate]);  // eslint-disable-line react-hooks/exhaustive-deps

    function handleSseEvent(type: string, payload: unknown, msgId: string) {
        switch (type) {
            case 'token': {
                const { text } = payload as TokenEvent;
                onMessageUpdate(msgs =>
                    msgs.map(m => m.id === msgId
                        ? { ...m, content: m.content + text }
                        : m
                    )
                );
                break;
            }
            case 'tool_start': {
                const { tool } = payload as ToolStartEvent;
                const activity: ToolActivity = { tool, status: 'running' };
                onMessageUpdate(msgs =>
                    msgs.map(m => m.id === msgId
                        ? { ...m, toolActivity: [...(m.toolActivity ?? []), activity] }
                        : m
                    )
                );
                break;
            }
            case 'tool_end': {
                const { tool, success, output } = payload as ToolEndEvent;
                onMessageUpdate(msgs =>
                    msgs.map(m => m.id === msgId ? {
                        ...m,
                        toolActivity: (m.toolActivity ?? []).map(a =>
                            a.tool === tool && a.status === 'running'
                                ? { ...a, status: success ? 'success' : 'error', output }
                                : a
                        ),
                    } : m)
                );
                break;
            }
            case 'self_correction': {
                const { message } = payload as SelfCorrectionEvent;
                onMessageUpdate(msgs =>
                    msgs.map(m => m.id === msgId
                        ? { ...m, isSelfCorrecting: true, content: m.content + `\n\n_🔄 ${message}_\n\n` }
                        : m
                    )
                );
                break;
            }
            case 'done': {
                const { session_id, final_text } = payload as DoneEvent & { final_text?: string };
                sessionIdRef.current = session_id;
                onSessionId(session_id);
                onMessageUpdate(msgs =>
                    msgs.map(m => m.id === msgId
                        ? {
                            ...m,
                            // If no tokens were streamed (ainvoke path), use final_text
                            content: m.content || final_text || '(No response)',
                            isStreaming: false,
                            isSelfCorrecting: false,
                        }
                        : m
                    )
                );
                break;
            }
            case 'error': {
                onMessageUpdate(msgs =>
                    msgs.map(m => m.id === msgId
                        ? { ...m, isStreaming: false, content: m.content || 'Something went wrong.' }
                        : m
                    )
                );
                break;
            }
        }
    }

    return { sendMessage, setGoogleToken };
}
