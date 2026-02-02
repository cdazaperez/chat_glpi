"""
Authentication service for JWT-based authentication with GLPI.

This service handles:
- User authentication via GLPI credentials
- JWT token generation and validation
- Token refresh functionality
"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple
from pydantic import BaseModel
import jwt
from jwt.exceptions import InvalidTokenError, ExpiredSignatureError

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class TokenPayload(BaseModel):
    """JWT token payload structure."""
    sub: str  # Subject (user_id from GLPI)
    email: str
    username: str
    name: str
    role: str  # 'admin' or 'technician'
    glpi_user_id: int
    exp: datetime
    iat: datetime
    jti: str  # JWT ID for token revocation


class AuthResult(BaseModel):
    """Authentication result."""
    success: bool
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_type: str = "Bearer"
    expires_in: Optional[int] = None  # seconds
    user: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class AuthService:
    """Service for handling authentication with GLPI and JWT tokens."""

    def __init__(self, glpi_client=None, cache=None):
        """
        Initialize the auth service.

        Args:
            glpi_client: GLPI client instance for user verification
            cache: Redis cache for token blacklisting
        """
        self.settings = get_settings()
        self.glpi = glpi_client
        self.cache = cache

        # Get JWT secret - use configured or generate a secure one
        self._jwt_secret = self.settings.auth.jwt_secret or self.settings.app.secret_key
        if not self._jwt_secret:
            logger.warning("No JWT secret configured, generating temporary one. Set AUTH_JWT_SECRET for production!")
            self._jwt_secret = secrets.token_urlsafe(32)

        self._token_expiry = self.settings.auth.token_expiry_minutes
        self._refresh_expiry = self._token_expiry * 24  # Refresh token lasts 24x longer
        self._algorithm = "HS256"

    async def authenticate(self, username: str, password: str) -> AuthResult:
        """
        Authenticate a user with GLPI credentials.

        Args:
            username: GLPI username
            password: GLPI password

        Returns:
            AuthResult with tokens if successful, error message if not
        """
        logger.info("Attempting authentication", data={"username": username})

        try:
            # Try to authenticate with GLPI
            auth_result = await self._verify_glpi_credentials(username, password)

            if not auth_result["success"]:
                logger.warning("Authentication failed", data={"username": username, "reason": auth_result.get("error")})
                return AuthResult(
                    success=False,
                    error=auth_result.get("error", "Invalid credentials")
                )

            user_data = auth_result["user"]

            # Generate tokens
            access_token, access_exp = self._generate_access_token(user_data)
            refresh_token, _ = self._generate_refresh_token(user_data)

            logger.info("Authentication successful", data={
                "username": username,
                "user_id": user_data.get("id"),
                "role": user_data.get("role")
            })

            return AuthResult(
                success=True,
                access_token=access_token,
                refresh_token=refresh_token,
                expires_in=self._token_expiry * 60,  # Convert to seconds
                user={
                    "id": user_data.get("id"),
                    "username": user_data.get("username"),
                    "email": user_data.get("email"),
                    "name": user_data.get("name"),
                    "role": user_data.get("role"),
                }
            )

        except Exception as e:
            logger.error(f"Authentication error: {e}", data={"username": username})
            return AuthResult(
                success=False,
                error="Authentication service error. Please try again."
            )

    async def _verify_glpi_credentials(self, username: str, password: str) -> Dict[str, Any]:
        """
        Verify credentials by attempting to authenticate with GLPI API.

        Args:
            username: GLPI username
            password: GLPI password

        Returns:
            Dict with success status and user data or error
        """
        import httpx

        glpi_settings = self.settings.glpi
        base_url = glpi_settings.base_url.rstrip("/")

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Initialize GLPI session with user credentials
                response = await client.get(
                    f"{base_url}/initSession",
                    auth=(username, password),
                    headers={
                        "Content-Type": "application/json",
                        "App-Token": glpi_settings.app_token,
                    }
                )

                if response.status_code == 401:
                    return {"success": False, "error": "Invalid username or password"}

                if response.status_code != 200:
                    logger.error(f"GLPI auth failed with status {response.status_code}")
                    return {"success": False, "error": "GLPI authentication failed"}

                session_data = response.json()
                session_token = session_data.get("session_token")

                if not session_token:
                    return {"success": False, "error": "Failed to get GLPI session"}

                # Get user profile from the session
                profile_response = await client.get(
                    f"{base_url}/getFullSession",
                    headers={
                        "Content-Type": "application/json",
                        "App-Token": glpi_settings.app_token,
                        "Session-Token": session_token,
                    }
                )

                if profile_response.status_code != 200:
                    # Still authenticated, but can't get profile - use basic info
                    user_data = {
                        "id": session_data.get("glpiID"),
                        "username": username,
                        "email": f"{username}@{glpi_settings.base_url.split('//')[1].split('/')[0]}",
                        "name": username,
                        "role": "technician"
                    }
                else:
                    session_info = profile_response.json().get("session", {})

                    # Determine role based on GLPI profiles
                    # Profile ID 4 is typically "Super-Admin" in GLPI
                    # Profile ID 3 is typically "Admin"
                    # Profile ID 2 is typically "Technician"
                    glpi_profiles = session_info.get("glpiactiveprofile", {})
                    profile_id = glpi_profiles.get("id", 0)

                    is_admin = profile_id in [3, 4] or glpi_profiles.get("interface", "") == "central"

                    user_data = {
                        "id": session_info.get("glpiID") or session_data.get("glpiID"),
                        "username": session_info.get("glpiname", username),
                        "email": session_info.get("glpiemail", ""),
                        "name": session_info.get("glpifriendlyname", session_info.get("glpirealname", username)),
                        "role": "admin" if is_admin else "technician"
                    }

                # Kill the session to clean up
                await client.get(
                    f"{base_url}/killSession",
                    headers={
                        "Content-Type": "application/json",
                        "App-Token": glpi_settings.app_token,
                        "Session-Token": session_token,
                    }
                )

                return {"success": True, "user": user_data}

        except httpx.TimeoutException:
            logger.error("GLPI authentication timeout")
            return {"success": False, "error": "GLPI server timeout"}
        except Exception as e:
            logger.error(f"GLPI authentication error: {e}")
            return {"success": False, "error": "Failed to connect to GLPI"}

    def _generate_access_token(self, user_data: Dict[str, Any]) -> Tuple[str, datetime]:
        """Generate an access token for the user."""
        now = datetime.now(timezone.utc)
        exp = now + timedelta(minutes=self._token_expiry)

        payload = {
            "sub": str(user_data["id"]),
            "email": user_data.get("email", ""),
            "username": user_data.get("username", ""),
            "name": user_data.get("name", ""),
            "role": user_data.get("role", "technician"),
            "glpi_user_id": user_data["id"],
            "exp": exp,
            "iat": now,
            "jti": secrets.token_urlsafe(16),
            "type": "access"
        }

        token = jwt.encode(payload, self._jwt_secret, algorithm=self._algorithm)
        return token, exp

    def _generate_refresh_token(self, user_data: Dict[str, Any]) -> Tuple[str, datetime]:
        """Generate a refresh token for the user."""
        now = datetime.now(timezone.utc)
        exp = now + timedelta(minutes=self._refresh_expiry)

        payload = {
            "sub": str(user_data["id"]),
            "glpi_user_id": user_data["id"],
            "exp": exp,
            "iat": now,
            "jti": secrets.token_urlsafe(16),
            "type": "refresh"
        }

        token = jwt.encode(payload, self._jwt_secret, algorithm=self._algorithm)
        return token, exp

    def validate_token(self, token: str) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """
        Validate a JWT token.

        Args:
            token: The JWT token to validate

        Returns:
            Tuple of (is_valid, payload, error_message)
        """
        try:
            payload = jwt.decode(
                token,
                self._jwt_secret,
                algorithms=[self._algorithm]
            )

            # Check if it's an access token
            if payload.get("type") != "access":
                return False, None, "Invalid token type"

            return True, payload, None

        except ExpiredSignatureError:
            return False, None, "Token has expired"
        except InvalidTokenError as e:
            logger.warning(f"Invalid token: {e}")
            return False, None, "Invalid token"

    async def refresh_access_token(self, refresh_token: str) -> AuthResult:
        """
        Generate a new access token using a refresh token.

        Args:
            refresh_token: The refresh token

        Returns:
            AuthResult with new access token if successful
        """
        try:
            payload = jwt.decode(
                refresh_token,
                self._jwt_secret,
                algorithms=[self._algorithm]
            )

            if payload.get("type") != "refresh":
                return AuthResult(success=False, error="Invalid token type")

            # Check if token is blacklisted
            if self.cache:
                is_blacklisted = await self.cache.get(f"auth:blacklist:{payload['jti']}")
                if is_blacklisted:
                    return AuthResult(success=False, error="Token has been revoked")

            # Generate new access token
            user_data = {
                "id": payload["glpi_user_id"],
                "username": payload.get("username", ""),
                "email": payload.get("email", ""),
                "name": payload.get("name", ""),
                "role": payload.get("role", "technician"),
            }

            # Re-fetch user info from GLPI to ensure it's current
            if self.glpi:
                try:
                    user = await self.glpi.get_user_by_email(user_data.get("email", ""))
                    if user:
                        profile = await self.glpi.get_user_profile(user["id"])
                        if profile:
                            user_data["role"] = profile.get("role", "technician")
                except Exception:
                    pass  # Use existing data if refresh fails

            access_token, _ = self._generate_access_token(user_data)

            return AuthResult(
                success=True,
                access_token=access_token,
                expires_in=self._token_expiry * 60
            )

        except ExpiredSignatureError:
            return AuthResult(success=False, error="Refresh token has expired")
        except InvalidTokenError:
            return AuthResult(success=False, error="Invalid refresh token")

    async def revoke_token(self, token: str) -> bool:
        """
        Revoke a token by adding it to the blacklist.

        Args:
            token: The token to revoke

        Returns:
            True if revoked successfully
        """
        try:
            payload = jwt.decode(
                token,
                self._jwt_secret,
                algorithms=[self._algorithm],
                options={"verify_exp": False}  # Allow revoking expired tokens
            )

            if self.cache:
                # Add to blacklist with expiry matching token expiry
                exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
                ttl = max(0, int((exp - datetime.now(timezone.utc)).total_seconds()))
                await self.cache.set(
                    f"auth:blacklist:{payload['jti']}",
                    "1",
                    ttl=ttl + 60  # Add buffer
                )

            logger.info("Token revoked", data={"jti": payload["jti"]})
            return True

        except Exception as e:
            logger.error(f"Error revoking token: {e}")
            return False


# Singleton instance
_auth_service: Optional[AuthService] = None


def get_auth_service(glpi_client=None, cache=None) -> AuthService:
    """Get or create the auth service singleton."""
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService(glpi_client=glpi_client, cache=cache)
    return _auth_service
