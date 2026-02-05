'use client';

import { Chat, LoginForm } from '@/components';
import { useAuth } from '@/hooks/useAuth';
import { Loader2 } from 'lucide-react';

export default function Home() {
  const glpiBaseUrl = process.env.NEXT_PUBLIC_GLPI_URL;

  const {
    user,
    isAuthenticated,
    authEnabled,
    isLoading,
    error,
    login,
    logout,
    clearError,
  } = useAuth();

  // Still checking auth status
  if (isLoading) {
    return (
      <main className="h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="w-8 h-8 text-primary-500 animate-spin" />
          <p className="text-sm text-gray-500 dark:text-gray-400">Loading...</p>
        </div>
      </main>
    );
  }

  // Auth is enabled and user is not authenticated — show login
  if (authEnabled && !isAuthenticated) {
    return (
      <main className="h-screen">
        <LoginForm
          onLogin={login}
          error={error}
          isLoading={isLoading}
          onClearError={clearError}
        />
      </main>
    );
  }

  // Authenticated (or auth disabled) — show chat
  return (
    <main className="h-screen">
      <Chat
        glpiBaseUrl={glpiBaseUrl}
        user={user}
        authEnabled={authEnabled ?? false}
        onLogout={logout}
      />
    </main>
  );
}
