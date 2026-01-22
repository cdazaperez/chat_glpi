// API service for Helpdesk AI

import {
  ChatRequest,
  ChatResponse,
  TicketCreateRequest,
  TicketCreateResponse,
  HealthStatus,
  ErrorResponse,
} from '@/types';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

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
  /**
   * Send a chat message and get AI response
   */
  async chat(request: ChatRequest): Promise<ChatResponse> {
    const response = await fetch(`${API_URL}/api/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(request),
    });

    return handleResponse<ChatResponse>(response);
  },

  /**
   * Create a support ticket
   */
  async createTicket(request: TicketCreateRequest): Promise<TicketCreateResponse> {
    const response = await fetch(`${API_URL}/api/ticket`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(request),
    });

    return handleResponse<TicketCreateResponse>(response);
  },

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
      headers: {
        'Content-Type': 'application/json',
      },
    });

    return handleResponse(response);
  },

  /**
   * Delete a session
   */
  async deleteSession(sessionId: string): Promise<void> {
    const response = await fetch(`${API_URL}/api/session/${sessionId}`, {
      method: 'DELETE',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      throw new ApiError('Failed to delete session', response.status);
    }
  },

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

export { ApiError };
