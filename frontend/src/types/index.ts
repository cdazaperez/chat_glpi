// Type definitions for Helpdesk AI Frontend

export type MessageRole = 'user' | 'assistant' | 'system';

export type ReferenceType = 'kb' | 'ticket';

export type ActionType = 'create_ticket' | 'escalate' | 'request_info';

export interface Reference {
  type: ReferenceType;
  id: number;
  title: string;
  relevance?: number;
  url?: string;
}

export interface SuggestedAction {
  type: ActionType;
  enabled: boolean;
  description?: string;
  prefilled?: {
    title?: string;
    description?: string;
    category_id?: number;
    urgency?: number;
    impact?: number;
  };
}

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  timestamp: Date;
  references?: Reference[];
  isLoading?: boolean;
}

export interface ChatContext {
  user_email?: string;
  department?: string;
  user_role?: string;
}

export interface ChatRequest {
  message: string;
  session_id?: string;
  context?: ChatContext;
}

export interface ResponseMetadata {
  correlation_id: string;
  processing_time_ms: number;
  sources_consulted: string[];
  tokens_used?: number;
  cache_hit: boolean;
}

export interface ChatResponse {
  response: string;
  session_id: string;
  references: Reference[];
  suggested_actions: SuggestedAction[];
  metadata: ResponseMetadata;
}

export interface TicketCreateRequest {
  title: string;
  description: string;
  requester_email?: string;
  category_id?: number;
  urgency?: number;
  impact?: number;
  session_id?: string;
}

export interface TicketCreateResponse {
  success: boolean;
  ticket_id?: number;
  ticket_url?: string;
  message: string;
}

export interface HealthStatus {
  status: string;
  timestamp: string;
  version: string;
  components: Record<string, string>;
}

export interface ErrorResponse {
  error: string;
  detail?: string;
  correlation_id?: string;
}

// Chat state
export interface ChatState {
  messages: ChatMessage[];
  sessionId: string | null;
  isLoading: boolean;
  error: string | null;
  suggestedActions: SuggestedAction[];
}

// Authentication types
export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  token: string;
  token_type: string;
  expires_in: number;
  user: AuthUser;
}

export interface AuthUser {
  id: string;
  username: string;
  email: string;
  firstname?: string;
  lastname?: string;
}

export interface AuthStatusResponse {
  authenticated: boolean;
  auth_enabled: boolean;
  user: AuthUser | null;
}

export interface AuthState {
  token: string | null;
  user: AuthUser | null;
  isAuthenticated: boolean;
  authEnabled: boolean | null;
  isLoading: boolean;
  error: string | null;
}
