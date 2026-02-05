// Custom hook for authentication

import { useState, useCallback, useEffect } from 'react';
import { api, ApiError, clearAuthToken } from '@/services/api';
import { AuthState, AuthUser } from '@/types';

const AUTH_USER_KEY = 'helpdesk_ai_user';

export function useAuth() {
  const [state, setState] = useState<AuthState>({
    token: null,
    user: null,
    isAuthenticated: false,
    authEnabled: null, // null = not yet checked
    isLoading: true,
    error: null,
  });

  // On mount, check if auth is enabled and if we have a valid token
  useEffect(() => {
    let cancelled = false;

    async function checkAuth() {
      try {
        const status = await api.authStatus();

        if (cancelled) return;

        if (!status.auth_enabled) {
          // Auth is disabled — allow access without login
          setState({
            token: null,
            user: null,
            isAuthenticated: true,
            authEnabled: false,
            isLoading: false,
            error: null,
          });
          return;
        }

        // Auth is enabled — check if current token is valid
        if (status.authenticated && status.user) {
          setState({
            token: null, // token is in localStorage, managed by api service
            user: status.user,
            isAuthenticated: true,
            authEnabled: true,
            isLoading: false,
            error: null,
          });
        } else {
          // Token is missing or invalid
          clearAuthToken();
          localStorage.removeItem(AUTH_USER_KEY);
          setState({
            token: null,
            user: null,
            isAuthenticated: false,
            authEnabled: true,
            isLoading: false,
            error: null,
          });
        }
      } catch (error) {
        if (cancelled) return;

        if (error instanceof ApiError && error.status === 401) {
          // Token expired or invalid
          clearAuthToken();
          localStorage.removeItem(AUTH_USER_KEY);
          setState({
            token: null,
            user: null,
            isAuthenticated: false,
            authEnabled: true,
            isLoading: false,
            error: null,
          });
        } else {
          // Network error or server down — try to use cached user
          const cachedUser = localStorage.getItem(AUTH_USER_KEY);
          const hasToken = api.hasToken();

          if (hasToken && cachedUser) {
            try {
              const user = JSON.parse(cachedUser) as AuthUser;
              setState({
                token: null,
                user,
                isAuthenticated: true,
                authEnabled: true,
                isLoading: false,
                error: null,
              });
              return;
            } catch {
              // Invalid cached data
            }
          }

          setState({
            token: null,
            user: null,
            isAuthenticated: false,
            authEnabled: true,
            isLoading: false,
            error: 'Unable to check authentication status. Please try again.',
          });
        }
      }
    }

    checkAuth();

    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    setState((prev) => ({ ...prev, isLoading: true, error: null }));

    try {
      const response = await api.login({ username, password });

      // Cache user info
      localStorage.setItem(AUTH_USER_KEY, JSON.stringify(response.user));

      setState({
        token: response.token,
        user: response.user,
        isAuthenticated: true,
        authEnabled: true,
        isLoading: false,
        error: null,
      });

      return true;
    } catch (error) {
      const message =
        error instanceof ApiError
          ? error.message
          : 'Login failed. Please try again.';

      setState((prev) => ({
        ...prev,
        isLoading: false,
        error: message,
      }));

      return false;
    }
  }, []);

  const logout = useCallback(() => {
    api.logout();
    localStorage.removeItem(AUTH_USER_KEY);
    localStorage.removeItem('helpdesk_ai_session');

    setState({
      token: null,
      user: null,
      isAuthenticated: false,
      authEnabled: true,
      isLoading: false,
      error: null,
    });
  }, []);

  const clearError = useCallback(() => {
    setState((prev) => ({ ...prev, error: null }));
  }, []);

  return {
    user: state.user,
    isAuthenticated: state.isAuthenticated,
    authEnabled: state.authEnabled,
    isLoading: state.isLoading,
    error: state.error,
    login,
    logout,
    clearError,
  };
}
