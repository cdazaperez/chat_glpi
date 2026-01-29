'use client';

import { useState, useEffect } from 'react';
import { Chat, UserLogin } from '@/components';
import { ChatContext } from '@/types';

const USER_CONTEXT_KEY = 'helpdesk_ai_user';

export default function Home() {
  // Get GLPI base URL from environment for reference links
  const glpiBaseUrl = process.env.NEXT_PUBLIC_GLPI_URL;

  // User context state
  const [userContext, setUserContext] = useState<ChatContext | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Load user context from localStorage on mount
  useEffect(() => {
    const stored = localStorage.getItem(USER_CONTEXT_KEY);
    if (stored) {
      try {
        const context = JSON.parse(stored) as ChatContext;
        setUserContext(context);
      } catch {
        localStorage.removeItem(USER_CONTEXT_KEY);
      }
    }
    setIsLoading(false);
  }, []);

  // Handle login
  const handleLogin = (context: ChatContext) => {
    setUserContext(context);
    localStorage.setItem(USER_CONTEXT_KEY, JSON.stringify(context));
  };

  // Handle logout
  const handleLogout = () => {
    setUserContext(null);
    localStorage.removeItem(USER_CONTEXT_KEY);
    // Also clear the chat session
    localStorage.removeItem('helpdesk_ai_session');
  };

  // Show loading state briefly to avoid flash
  if (isLoading) {
    return (
      <main className="h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900">
        <div className="animate-pulse text-gray-400">Cargando...</div>
      </main>
    );
  }

  // Show login if no user context
  if (!userContext) {
    return (
      <main className="h-screen">
        <UserLogin onLogin={handleLogin} />
      </main>
    );
  }

  // Show chat with user context
  return (
    <main className="h-screen">
      <Chat
        glpiBaseUrl={glpiBaseUrl}
        userContext={userContext}
        onLogout={handleLogout}
      />
    </main>
  );
}
