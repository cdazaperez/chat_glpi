'use client';

import React, { useState, useRef, useEffect } from 'react';
import { Send, Loader2 } from 'lucide-react';
import { clsx } from 'clsx';

interface ChatInputProps {
  onSend: (message: string) => void;
  isLoading: boolean;
  disabled?: boolean;
  placeholder?: string;
  maxLength?: number;
}

export function ChatInput({
  onSend,
  isLoading,
  disabled = false,
  placeholder = 'Describe your issue or ask a question...',
  maxLength = 4000,
}: ChatInputProps) {
  const [message, setMessage] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea
  useEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = 'auto';
      textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`;
    }
  }, [message]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (message.trim() && !isLoading && !disabled) {
      onSend(message);
      setMessage('');
      if (textareaRef.current) {
        textareaRef.current.style.height = 'auto';
      }
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const remainingChars = maxLength - message.length;
  const isNearLimit = remainingChars < 200;

  return (
    <form onSubmit={handleSubmit} className="relative">
      <div className="relative flex items-end bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg shadow-sm focus-within:ring-2 focus-within:ring-primary-500 focus-within:border-primary-500">
        <textarea
          ref={textareaRef}
          value={message}
          onChange={(e) => setMessage(e.target.value.slice(0, maxLength))}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={disabled || isLoading}
          rows={1}
          className={clsx(
            'flex-1 w-full px-4 py-3 pr-12 bg-transparent border-0 resize-none focus:ring-0 focus:outline-none',
            'text-gray-900 dark:text-gray-100 placeholder-gray-500 dark:placeholder-gray-400',
            'disabled:opacity-50 disabled:cursor-not-allowed'
          )}
          style={{ minHeight: '48px', maxHeight: '200px' }}
        />

        <button
          type="submit"
          disabled={!message.trim() || isLoading || disabled}
          className={clsx(
            'absolute right-2 bottom-2 p-2 rounded-lg transition-colors',
            'focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2',
            message.trim() && !isLoading && !disabled
              ? 'bg-primary-500 text-white hover:bg-primary-600'
              : 'bg-gray-200 dark:bg-gray-700 text-gray-400 cursor-not-allowed'
          )}
          aria-label="Send message"
        >
          {isLoading ? (
            <Loader2 className="w-5 h-5 animate-spin" />
          ) : (
            <Send className="w-5 h-5" />
          )}
        </button>
      </div>

      {/* Character count */}
      <div className="flex justify-between items-center mt-1 px-1">
        <span className="text-xs text-gray-500 dark:text-gray-400">
          Press Enter to send, Shift+Enter for new line
        </span>
        {isNearLimit && (
          <span
            className={clsx(
              'text-xs',
              remainingChars < 100
                ? 'text-red-500'
                : 'text-yellow-500 dark:text-yellow-400'
            )}
          >
            {remainingChars} characters remaining
          </span>
        )}
      </div>
    </form>
  );
}
