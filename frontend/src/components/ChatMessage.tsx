'use client';

import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { clsx } from 'clsx';
import { User, Bot, ExternalLink, Copy, Check } from 'lucide-react';
import { ChatMessage as ChatMessageType, Reference } from '@/types';

interface ChatMessageProps {
  message: ChatMessageType;
  glpiBaseUrl?: string;
}

function ReferenceLink({ reference, glpiBaseUrl }: { reference: Reference; glpiBaseUrl?: string }) {
  const getUrl = () => {
    if (reference.url) return reference.url;
    if (!glpiBaseUrl) return null;

    if (reference.type === 'kb') {
      return `${glpiBaseUrl}/front/knowbaseitem.form.php?id=${reference.id}`;
    } else if (reference.type === 'ticket') {
      return `${glpiBaseUrl}/front/ticket.form.php?id=${reference.id}`;
    }
    return null;
  };

  const url = getUrl();
  const label = reference.type === 'kb' ? `KB #${reference.id}` : `Ticket #${reference.id}`;

  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium',
        reference.type === 'kb'
          ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300'
          : 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300'
      )}
    >
      {url ? (
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1 hover:underline"
          title={reference.title}
        >
          {label}
          <ExternalLink className="w-3 h-3" />
        </a>
      ) : (
        <span title={reference.title}>{label}</span>
      )}
    </span>
  );
}

function LoadingDots() {
  return (
    <div className="flex items-center gap-1">
      <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
      <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
      <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
    </div>
  );
}

export function ChatMessage({ message, glpiBaseUrl }: ChatMessageProps) {
  const [copied, setCopied] = React.useState(false);
  const isUser = message.role === 'user';

  const handleCopy = async () => {
    await navigator.clipboard.writeText(message.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div
      className={clsx(
        'flex gap-3 p-4 rounded-lg',
        isUser
          ? 'bg-primary-50 dark:bg-primary-900/20'
          : 'bg-gray-50 dark:bg-gray-800/50'
      )}
    >
      {/* Avatar */}
      <div
        className={clsx(
          'flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center',
          isUser
            ? 'bg-primary-500 text-white'
            : 'bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-300'
        )}
      >
        {isUser ? <User className="w-5 h-5" /> : <Bot className="w-5 h-5" />}
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        {/* Header */}
        <div className="flex items-center gap-2 mb-1">
          <span className="font-medium text-sm text-gray-900 dark:text-gray-100">
            {isUser ? 'You' : 'Helpdesk AI'}
          </span>
          <span className="text-xs text-gray-500 dark:text-gray-400">
            {message.timestamp.toLocaleTimeString()}
          </span>
        </div>

        {/* Message content */}
        {message.isLoading ? (
          <div className="py-2">
            <LoadingDots />
            <span className="text-sm text-gray-500 dark:text-gray-400 ml-2">
              Searching GLPI...
            </span>
          </div>
        ) : (
          <>
            <div className="prose prose-sm dark:prose-invert max-w-none">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  // Custom rendering for code blocks
                  code: ({ className, children, ...props }) => {
                    const isInline = !className;
                    return isInline ? (
                      <code
                        className="px-1 py-0.5 bg-gray-200 dark:bg-gray-700 rounded text-sm"
                        {...props}
                      >
                        {children}
                      </code>
                    ) : (
                      <code
                        className={clsx(className, 'block p-3 bg-gray-900 text-gray-100 rounded-lg overflow-x-auto')}
                        {...props}
                      >
                        {children}
                      </code>
                    );
                  },
                  // Make links open in new tab
                  a: ({ href, children }) => (
                    <a
                      href={href}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-primary-600 dark:text-primary-400 hover:underline"
                    >
                      {children}
                    </a>
                  ),
                }}
              >
                {message.content}
              </ReactMarkdown>
            </div>

            {/* References */}
            {message.references && message.references.length > 0 && (
              <div className="mt-3 pt-3 border-t border-gray-200 dark:border-gray-700">
                <span className="text-xs text-gray-500 dark:text-gray-400 mr-2">
                  Sources:
                </span>
                <div className="flex flex-wrap gap-2 mt-1">
                  {message.references.map((ref, idx) => (
                    <ReferenceLink
                      key={`${ref.type}-${ref.id}-${idx}`}
                      reference={ref}
                      glpiBaseUrl={glpiBaseUrl}
                    />
                  ))}
                </div>
              </div>
            )}

            {/* Copy button for assistant messages */}
            {!isUser && (
              <button
                onClick={handleCopy}
                className="mt-2 flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 transition-colors"
              >
                {copied ? (
                  <>
                    <Check className="w-3 h-3" />
                    Copied!
                  </>
                ) : (
                  <>
                    <Copy className="w-3 h-3" />
                    Copy response
                  </>
                )}
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}
