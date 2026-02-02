'use client';

import React, { useEffect, useRef } from 'react';
import { clsx } from 'clsx';
import {
  MessageSquare,
  Trash2,
  RefreshCw,
  AlertCircle,
  X,
  Ticket,
  HelpCircle,
  User,
} from 'lucide-react';
import { useChat } from '@/hooks/useChat';
import { ChatMessage } from './ChatMessage';
import { ChatInput } from './ChatInput';
import { SuggestedAction, ChatContext } from '@/types';

interface ChatProps {
  glpiBaseUrl?: string;
  userContext?: ChatContext;
  onLogout?: () => void;
  userName?: string;
  userRole?: string;
}

function WelcomeMessage() {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center px-4">
      <div className="w-16 h-16 bg-primary-100 dark:bg-primary-900/30 rounded-full flex items-center justify-center mb-4">
        <MessageSquare className="w-8 h-8 text-primary-600 dark:text-primary-400" />
      </div>
      <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100 mb-2">
        Welcome to Helpdesk AI
      </h2>
      <p className="text-gray-600 dark:text-gray-400 max-w-md mb-6">
        I can help you find solutions from our knowledge base and resolved tickets.
        Describe your issue or ask a question to get started.
      </p>
      <div className="grid gap-2 w-full max-w-sm">
        <ExamplePrompt text="How do I reset my password?" />
        <ExamplePrompt text="My email is not syncing" />
        <ExamplePrompt text="VPN connection issues" />
      </div>
    </div>
  );
}

function ExamplePrompt({ text }: { text: string }) {
  return (
    <button
      className="flex items-center gap-2 px-4 py-2 text-left text-sm text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-gray-800 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors"
    >
      <HelpCircle className="w-4 h-4 flex-shrink-0 text-gray-400" />
      {text}
    </button>
  );
}

function ErrorBanner({
  error,
  onDismiss,
  onRetry,
}: {
  error: string;
  onDismiss: () => void;
  onRetry: () => void;
}) {
  return (
    <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 mb-4">
      <div className="flex items-start gap-3">
        <AlertCircle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
        <div className="flex-1">
          <p className="text-sm text-red-800 dark:text-red-200">{error}</p>
          <div className="flex gap-2 mt-2">
            <button
              onClick={onRetry}
              className="flex items-center gap-1 text-xs text-red-700 dark:text-red-300 hover:text-red-900 dark:hover:text-red-100"
            >
              <RefreshCw className="w-3 h-3" />
              Retry
            </button>
          </div>
        </div>
        <button
          onClick={onDismiss}
          className="text-red-500 hover:text-red-700 dark:hover:text-red-300"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}

function SuggestedActions({
  actions,
  onAction,
}: {
  actions: SuggestedAction[];
  onAction: (action: SuggestedAction) => void;
}) {
  if (actions.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-2 mb-4">
      {actions.map((action, idx) => (
        <button
          key={idx}
          onClick={() => onAction(action)}
          disabled={!action.enabled}
          className={clsx(
            'flex items-center gap-2 px-3 py-2 text-sm rounded-lg border transition-colors',
            action.enabled
              ? 'border-primary-300 dark:border-primary-700 text-primary-700 dark:text-primary-300 hover:bg-primary-50 dark:hover:bg-primary-900/20'
              : 'border-gray-200 dark:border-gray-700 text-gray-400 cursor-not-allowed'
          )}
        >
          {action.type === 'create_ticket' && <Ticket className="w-4 h-4" />}
          {action.description || 'Create a support ticket'}
        </button>
      ))}
    </div>
  );
}

export function Chat({ glpiBaseUrl, userContext, onLogout, userName, userRole }: ChatProps) {
  const {
    messages,
    isLoading,
    error,
    suggestedActions,
    sendMessage,
    clearChat,
    clearError,
    retryLastMessage,
  } = useChat({ context: userContext });

  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSuggestedAction = (action: SuggestedAction) => {
    if (action.type === 'create_ticket') {
      sendMessage('I would like to create a support ticket for this issue.');
    }
  };

  // Display name - prefer userName prop, then email from context
  const displayName = userName || userContext?.user_email || 'Usuario';
  const displayRole = userRole || userContext?.user_role;

  return (
    <div className="flex flex-col h-full bg-white dark:bg-gray-900">
      {/* Header */}
      <header className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-primary-500 rounded-lg flex items-center justify-center">
            <MessageSquare className="w-6 h-6 text-white" />
          </div>
          <div>
            <h1 className="font-semibold text-gray-900 dark:text-gray-100">
              {process.env.NEXT_PUBLIC_APP_TITLE || 'Helpdesk AI'}
            </h1>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              {process.env.NEXT_PUBLIC_COMPANY_NAME || 'SkillNet'} Support
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {(userName || userContext?.user_email) && (
            <div className="flex items-center gap-2 px-3 py-2 text-sm text-gray-600 dark:text-gray-400 bg-gray-100 dark:bg-gray-800 rounded-lg">
              <User className="w-4 h-4" />
              <span className="hidden sm:inline max-w-[150px] truncate" title={displayName}>
                {displayName}
              </span>
              {displayRole && (
                <span className="text-xs px-2 py-0.5 bg-primary-100 dark:bg-primary-900/30 text-primary-700 dark:text-primary-300 rounded-full">
                  {displayRole}
                </span>
              )}
              {onLogout && (
                <button
                  onClick={onLogout}
                  className="ml-1 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
                  title="Cerrar sesión"
                >
                  <X className="w-4 h-4" />
                </button>
              )}
            </div>
          )}

          {messages.length > 0 && (
            <button
              onClick={clearChat}
              className="flex items-center gap-2 px-3 py-2 text-sm text-gray-600 dark:text-gray-400 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-colors"
              title="Clear conversation"
            >
              <Trash2 className="w-4 h-4" />
              <span className="hidden sm:inline">Clear</span>
            </button>
          )}
        </div>
      </header>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 ? (
          <WelcomeMessage />
        ) : (
          <>
            {messages.map((message) => (
              <ChatMessage
                key={message.id}
                message={message}
                glpiBaseUrl={glpiBaseUrl}
              />
            ))}
            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      {/* Footer */}
      <footer className="border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50 p-4">
        {error && (
          <ErrorBanner
            error={error}
            onDismiss={clearError}
            onRetry={retryLastMessage}
          />
        )}

        <SuggestedActions actions={suggestedActions} onAction={handleSuggestedAction} />

        <ChatInput onSend={sendMessage} isLoading={isLoading} />

        <p className="mt-2 text-xs text-center text-gray-500 dark:text-gray-400">
          Responses are generated using AI and GLPI data. Always verify critical information.
        </p>
      </footer>
    </div>
  );
}
