// Authentication service for Helpdesk AI Frontend

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// Storage keys
const TOKEN_KEY = 'helpdesk_ai_token';
const REFRESH_TOKEN_KEY = 'helpdesk_ai_refresh_token';
const USER_KEY = 'helpdesk_ai_user';

export interface AuthUser {
  id: number;
  username: string;
  email: string;
  name: string;
  role: 'admin' | 'technician';
}

export interface LoginResponse {
  success: boolean;
  access_token?: string;
  refresh_token?: string;
  token_type?: string;
  expires_in?: number;
  user?: AuthUser;
  error?: string;
}

export interface AuthConfig {
  enabled: boolean;
  token_expiry_minutes?: number;
}

class AuthService {
  private tokenRefreshPromise: Promise<string | null> | null = null;

  /**
   * Get authentication configuration from backend
   */
  async getAuthConfig(): Promise<AuthConfig> {
    try {
      const response = await fetch(`${API_URL}/api/auth/config`);
      if (response.ok) {
        return await response.json();
      }
      return { enabled: false };
    } catch {
      return { enabled: false };
    }
  }

  /**
   * Login with GLPI credentials
   */
  async login(username: string, password: string): Promise<LoginResponse> {
    try {
      const response = await fetch(`${API_URL}/api/auth/login`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ username, password }),
      });

      const data: LoginResponse = await response.json();

      if (data.success && data.access_token) {
        this.setTokens(data.access_token, data.refresh_token);
        if (data.user) {
          this.setUser(data.user);
        }
      }

      return data;
    } catch (error) {
      console.error('Login error:', error);
      return {
        success: false,
        error: 'No se pudo conectar al servidor. Por favor, intenta de nuevo.',
      };
    }
  }

  /**
   * Logout and clear tokens
   */
  async logout(): Promise<void> {
    const refreshToken = this.getRefreshToken();

    try {
      const token = this.getAccessToken();
      if (token) {
        await fetch(`${API_URL}/api/auth/logout`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`,
          },
          body: JSON.stringify({ refresh_token: refreshToken }),
        });
      }
    } catch {
      // Ignore logout errors
    } finally {
      this.clearTokens();
    }
  }

  /**
   * Refresh the access token
   */
  async refreshAccessToken(): Promise<string | null> {
    // Prevent multiple simultaneous refresh requests
    if (this.tokenRefreshPromise) {
      return this.tokenRefreshPromise;
    }

    this.tokenRefreshPromise = this._doRefresh();
    const result = await this.tokenRefreshPromise;
    this.tokenRefreshPromise = null;
    return result;
  }

  private async _doRefresh(): Promise<string | null> {
    const refreshToken = this.getRefreshToken();
    if (!refreshToken) {
      return null;
    }

    try {
      const response = await fetch(`${API_URL}/api/auth/refresh`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });

      if (response.ok) {
        const data = await response.json();
        if (data.success && data.access_token) {
          this.setAccessToken(data.access_token);
          return data.access_token;
        }
      }

      // Refresh failed - clear tokens
      this.clearTokens();
      return null;
    } catch {
      return null;
    }
  }

  /**
   * Get the current access token
   */
  getAccessToken(): string | null {
    if (typeof window === 'undefined') return null;
    return localStorage.getItem(TOKEN_KEY);
  }

  /**
   * Get the refresh token
   */
  getRefreshToken(): string | null {
    if (typeof window === 'undefined') return null;
    return localStorage.getItem(REFRESH_TOKEN_KEY);
  }

  /**
   * Get the current user
   */
  getUser(): AuthUser | null {
    if (typeof window === 'undefined') return null;
    const userStr = localStorage.getItem(USER_KEY);
    if (userStr) {
      try {
        return JSON.parse(userStr);
      } catch {
        return null;
      }
    }
    return null;
  }

  /**
   * Check if user is authenticated
   */
  isAuthenticated(): boolean {
    return !!this.getAccessToken();
  }

  /**
   * Set access token
   */
  setAccessToken(token: string): void {
    if (typeof window !== 'undefined') {
      localStorage.setItem(TOKEN_KEY, token);
    }
  }

  /**
   * Set tokens
   */
  setTokens(accessToken: string, refreshToken?: string): void {
    if (typeof window !== 'undefined') {
      localStorage.setItem(TOKEN_KEY, accessToken);
      if (refreshToken) {
        localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
      }
    }
  }

  /**
   * Set user data
   */
  setUser(user: AuthUser): void {
    if (typeof window !== 'undefined') {
      localStorage.setItem(USER_KEY, JSON.stringify(user));
    }
  }

  /**
   * Clear all tokens and user data
   */
  clearTokens(): void {
    if (typeof window !== 'undefined') {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(REFRESH_TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
    }
  }

  /**
   * Get authorization header for API requests
   */
  getAuthHeader(): Record<string, string> {
    const token = this.getAccessToken();
    if (token) {
      return { 'Authorization': `Bearer ${token}` };
    }
    return {};
  }
}

// Singleton instance
export const authService = new AuthService();
