// Types for SSE events from the backend
export type SseEventType =
  | 'token'
  | 'tool_start'
  | 'tool_end'
  | 'self_correction'
  | 'done'
  | 'error';

export interface TokenEvent { text: string }
export interface ToolStartEvent { tool: string; input: Record<string, unknown> }
export interface ToolEndEvent { tool: string; output: unknown; success: boolean }
export interface SelfCorrectionEvent { message: string }
export interface DoneEvent { session_id: string }
export interface ErrorEvent { message: string }

export type SsePayload =
  | TokenEvent
  | ToolStartEvent
  | ToolEndEvent
  | SelfCorrectionEvent
  | DoneEvent
  | ErrorEvent;

// Chat message types
export type Role = 'user' | 'assistant';

export interface ToolActivity {
  tool: string;
  status: 'running' | 'success' | 'error';
  output?: unknown;
}

export interface Message {
  id: string;
  role: Role;
  content: string;
  toolActivity?: ToolActivity[];
  isSelfCorrecting?: boolean;
  isStreaming?: boolean;
  timestamp: Date;
}
