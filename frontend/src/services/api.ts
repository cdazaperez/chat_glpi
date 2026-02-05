// API service for Helpdesk AI

import {
  ChatRequest,
  ChatResponse,
  TicketCreateRequest,
  TicketCreateResponse,
  HealthStatus,
  ErrorResponse,
  LoginRequest,
  LoginResponse,
  AuthStatusResponse,
} from '@/types';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const AUTH_TOKEN_KEY = 'helpdesk_ai_token';

class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public correlationId?: string
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

function getAuthToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(AUTH_TOKEN_KEY);
}

function setAuthToken(token: string): void {
  localStorage.setItem(AUTH_TOKEN_KEY, token);
}

function clearAuthToken(): void {
  localStorage.removeItem(AUTH_TOKEN_KEY);
}

function getAuthHeaders(): Record<string, string> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  const token = getAuthToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

async function handleResponse<T>(response: Response): Promise<T> {
  const correlationId = response.headers.get('X-Correlation-ID') || undefined;

  if (!response.ok) {
    let errorMessage = 'An error occurred';

    try {
      const errorData: ErrorResponse = await response.json();
      errorMessage = errorData.detail || errorData.error || errorMessage;
    } catch {
      errorMessage = `HTTP Error: ${response.status}`;
    }

    throw new ApiError(errorMessage, response.status, correlationId);
  }

  return response.json();
}

export const api = {
  // --- Authentication ---

  /**
   * Log in with GLPI credentials
   */
  async login(request: LoginRequest): Promise<LoginResponse> {
    const response = await fetch(`${API_URL}/api/auth/login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(request),
    });

    const data = await handleResponse<LoginResponse>(response);
    setAuthToken(data.token);
    return data;
  },

  /**
   * Log out — clear stored token
   */
  logout(): void {
    clearAuthToken();
  },

  /**
   * Check authentication status
   */
  async authStatus(): Promise<AuthStatusResponse> {
    const response = await fetch(`${API_URL}/api/auth/status`, {
      method: 'GET',
      headers: getAuthHeaders(),
    });

    return handleResponse<AuthStatusResponse>(response);
  },

  /**
   * Check if a token is stored locally
   */
  hasToken(): boolean {
    return getAuthToken() !== null;
  },

  // --- Chat ---

  /**
   * Send a chat message and get AI response
   */
  async chat(request: ChatRequest): Promise<ChatResponse> {
    const response = await fetch(`${API_URL}/api/chat`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify(request),
    });

    return handleResponse<ChatResponse>(response);
  },

  // --- Tickets ---

  /**
   * Create a support ticket
   */
  async createTicket(request: TicketCreateRequest): Promise<TicketCreateResponse> {
    const response = await fetch(`${API_URL}/api/ticket`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify(request),
    });

    return handleResponse<TicketCreateResponse>(response);
  },

  // --- Sessions ---

  /**
   * Get session history
   */
  async getSession(sessionId: string): Promise<{
    session_id: string;
    messages: Array<{
      role: string;
      content: string;
      timestamp: string;
      references: Array<{
        type: string;
        id: number;
        title: string;
      }>;
    }>;
    created_at: string;
    updated_at: string;
  }> {
    const response = await fetch(`${API_URL}/api/session/${sessionId}`, {
      method: 'GET',
      headers: getAuthHeaders(),
    });

    return handleResponse(response);
  },

  /**
   * Delete a session
   */
  async deleteSession(sessionId: string): Promise<void> {
    const response = await fetch(`${API_URL}/api/session/${sessionId}`, {
      method: 'DELETE',
      headers: getAuthHeaders(),
    });

    if (!response.ok) {
      throw new ApiError('Failed to delete session', response.status);
    }
  },

  // --- Health ---

  /**
   * Check API health
   */
  async healthCheck(): Promise<HealthStatus> {
    const response = await fetch(`${API_URL}/health`, {
      method: 'GET',
    });

    return handleResponse<HealthStatus>(response);
  },

  /**
   * Check API readiness
   */
  async readinessCheck(): Promise<HealthStatus> {
    const response = await fetch(`${API_URL}/health/ready`, {
      method: 'GET',
    });

    return handleResponse<HealthStatus>(response);
  },
};

export { ApiError, clearAuthToken };
