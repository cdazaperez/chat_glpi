// Custom hook for chat functionality

import { useState, useCallback, useRef, useEffect } from 'react';
import { v4 as uuidv4 } from 'uuid';
import { api, ApiError } from '@/services/api';
import {
  ChatMessage,
  ChatState,
  SuggestedAction,
  Reference,
  ChatContext,
} from '@/types';

const STORAGE_KEY = 'helpdesk_ai_session';

interface UseChatOptions {
  context?: ChatContext;
  onError?: (error: string) => void;
}

export function useChat(options: UseChatOptions = {}) {
  const [state, setState] = useState<ChatState>({
    messages: [],
    sessionId: null,
    isLoading: false,
    error: null,
    suggestedActions: [],
  });

  const abortControllerRef = useRef<AbortController | null>(null);

  // Load session from storage on mount
  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      try {
        const data = JSON.parse(stored);
        setState((prev) => ({
          ...prev,
          sessionId: data.sessionId,
          messages: data.messages?.map((m: ChatMessage) => ({
            ...m,
            timestamp: new Date(m.timestamp),
          })) || [],
        }));
      } catch {
        localStorage.removeItem(STORAGE_KEY);
      }
    }
  }, []);

  // Save session to storage
  useEffect(() => {
    if (state.sessionId && state.messages.length > 0) {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({
          sessionId: state.sessionId,
          messages: state.messages.slice(-20), // Keep last 20 messages
        })
      );
    }
  }, [state.sessionId, state.messages]);

  const sendMessage = useCallback(
    async (content: string) => {
      if (!content.trim() || state.isLoading) {
        return;
      }

      // Cancel any pending request
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      abortControllerRef.current = new AbortController();

      // Add user message
      const userMessage: ChatMessage = {
        id: uuidv4(),
        role: 'user',
        content: content.trim(),
        timestamp: new Date(),
      };

      // Add loading message
      const loadingMessage: ChatMessage = {
        id: uuidv4(),
        role: 'assistant',
        content: '',
        timestamp: new Date(),
        isLoading: true,
      };

      setState((prev) => ({
        ...prev,
        messages: [...prev.messages, userMessage, loadingMessage],
        isLoading: true,
        error: null,
        suggestedActions: [],
      }));

      try {
        const response = await api.chat({
          message: content.trim(),
          session_id: state.sessionId || undefined,
          context: options.context,
        });

        // Create assistant message with response
        const assistantMessage: ChatMessage = {
          id: uuidv4(),
          role: 'assistant',
          content: response.response,
          timestamp: new Date(),
          references: response.references,
        };

        setState((prev) => ({
          ...prev,
          messages: prev.messages
            .filter((m) => !m.isLoading)
            .concat(assistantMessage),
          sessionId: response.session_id,
          isLoading: false,
          suggestedActions: response.suggested_actions,
        }));
      } catch (error) {
        // Remove loading message
        setState((prev) => ({
          ...prev,
          messages: prev.messages.filter((m) => !m.isLoading),
          isLoading: false,
          error:
            error instanceof ApiError
              ? error.message
              : 'Failed to send message. Please try again.',
        }));

        if (options.onError) {
          options.onError(
            error instanceof Error ? error.message : 'Unknown error'
          );
        }
      }
    },
    [state.sessionId, state.isLoading, options]
  );

  const clearChat = useCallback(() => {
    if (state.sessionId) {
      api.deleteSession(state.sessionId).catch(console.error);
    }

    localStorage.removeItem(STORAGE_KEY);

    setState({
      messages: [],
      sessionId: null,
      isLoading: false,
      error: null,
      suggestedActions: [],
    });
  }, [state.sessionId]);

  const clearError = useCallback(() => {
    setState((prev) => ({ ...prev, error: null }));
  }, []);

  const retryLastMessage = useCallback(() => {
    const lastUserMessage = [...state.messages]
      .reverse()
      .find((m) => m.role === 'user');

    if (lastUserMessage) {
      // Remove the last user message and any assistant message after it
      const lastUserIndex = state.messages.findIndex(
        (m) => m.id === lastUserMessage.id
      );
      setState((prev) => ({
        ...prev,
        messages: prev.messages.slice(0, lastUserIndex),
        error: null,
      }));

      // Resend
      sendMessage(lastUserMessage.content);
    }
  }, [state.messages, sendMessage]);

  return {
    messages: state.messages,
    sessionId: state.sessionId,
    isLoading: state.isLoading,
    error: state.error,
    suggestedActions: state.suggestedActions,
    sendMessage,
    clearChat,
    clearError,
    retryLastMessage,
  };
}
