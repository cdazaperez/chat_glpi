'use client';

import { useState, useEffect, useCallback } from 'react';
import { Chat, UserLogin } from '@/components';
import { ChatContext } from '@/types';
import { authService, AuthUser } from '@/services/auth';

export default function Home() {
  // Get GLPI base URL from environment for reference links
  const glpiBaseUrl = process.env.NEXT_PUBLIC_GLPI_URL;

  // User state
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [authEnabled, setAuthEnabled] = useState(true);

  // Check authentication status on mount
  useEffect(() => {
    const checkAuth = async () => {
      // Check if auth is enabled
      const config = await authService.getAuthConfig();
      setAuthEnabled(config.enabled);

      if (!config.enabled) {
        // Auth disabled - auto login as guest
        setUser({
          id: 0,
          username: 'guest',
          email: '',
          name: 'Usuario',
          role: 'technician',
        });
        setIsLoading(false);
        return;
      }

      // Check for existing valid session
      const existingUser = authService.getUser();
      const token = authService.getAccessToken();

      if (existingUser && token) {
        setUser(existingUser);
      }

      setIsLoading(false);
    };

    checkAuth();
  }, []);

  // Handle login - memoized to avoid unnecessary re-renders
  const handleLogin = useCallback((loggedInUser: AuthUser) => {
    setUser(loggedInUser);
  }, []);

  // Handle logout
  const handleLogout = useCallback(async () => {
    await authService.logout();
    setUser(null);
    // Also clear the chat session
    localStorage.removeItem('helpdesk_ai_session');
  }, []);

  // Convert AuthUser to ChatContext for the Chat component
  const getUserContext = useCallback((): ChatContext => {
    if (!user) {
      return {};
    }
    return {
      user_email: user.email || `${user.username}@local`,
      user_role: user.role,
    };
  }, [user]);

  // Show loading state briefly to avoid flash
  if (isLoading) {
    return (
      <main className="h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900">
        <div className="animate-pulse text-gray-400">Cargando...</div>
      </main>
    );
  }

  // Show login if no user
  if (!user) {
    return (
      <main className="h-screen">
        <UserLogin onLogin={handleLogin} authEnabled={authEnabled} />
      </main>
    );
  }

  // Show chat with user context
  return (
    <main className="h-screen">
      <Chat
        glpiBaseUrl={glpiBaseUrl}
        userContext={getUserContext()}
        onLogout={handleLogout}
        userName={user.name || user.username}
        userRole={user.role}
      />
    </main>
  );
}
