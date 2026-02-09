"""
Authentication service for Helpdesk AI.
Handles JWT token creation/validation and user authentication via GLPI.
"""
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

import jwt
import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class AuthError(Exception):
    """Authentication error."""
    pass


class TokenPayload:
    """Parsed JWT token payload."""

    def __init__(self, user_id: str, username: str, email: Optional[str] = None,
                 exp: Optional[datetime] = None):
        self.user_id = user_id
        self.username = username
        self.email = email
        self.exp = exp


class AuthService:
    """
    Service for authenticating users against GLPI and managing JWT tokens.

    Flow:
    1. User submits GLPI username/password
    2. Backend validates credentials by calling GLPI initSession with those credentials
    3. On success, backend issues a JWT token with user info
    4. Subsequent requests include the JWT in the Authorization header
    """

    def __init__(self):
        self.settings = get_settings()
        self._jwt_secret = self.settings.auth.jwt_secret or self.settings.app.secret_key
        self._token_expiry = self.settings.auth.token_expiry_minutes
        self._glpi_base_url = self.settings.glpi.base_url
        self._glpi_app_token = self.settings.glpi.app_token

        if not self._jwt_secret:
            raise AuthError(
                "JWT secret not configured. Set AUTH_JWT_SECRET or APP_SECRET_KEY."
            )

    async def authenticate_with_glpi(
        self, username: str, password: str
    ) -> Dict[str, Any]:
        """
        Authenticate a user by validating credentials against GLPI.

        Args:
            username: GLPI username
            password: GLPI password

        Returns:
            Dict with user info from GLPI session

        Raises:
            AuthError: If credentials are invalid or GLPI is unreachable
        """
        logger.info("Authenticating user against GLPI", data={"username": username})

        async with httpx.AsyncClient(timeout=httpx.Timeout(15)) as client:
            try:
                response = await client.get(
                    f"{self._glpi_base_url}/apirest.php/initSession",
                    headers={
                        "Content-Type": "application/json",
                        "App-Token": self._glpi_app_token,
                    },
                    auth=(username, password),
                )

                if response.status_code == 401:
                    logger.warning(
                        "GLPI authentication failed: invalid credentials",
                        data={"username": username},
                    )
                    raise AuthError("Invalid username or password")

                if response.status_code == 400:
                    error_data = response.json()
                    error_msg = error_data.get("1", error_data.get("message", "Authentication failed"))
                    logger.warning(
                        "GLPI authentication error",
                        data={"username": username, "error": str(error_msg)},
                    )
                    raise AuthError(f"Authentication error: {error_msg}")

                response.raise_for_status()
                session_data = response.json()
                session_token = session_data.get("session_token")

                if not session_token:
                    raise AuthError("GLPI did not return a session token")

                # Get user profile info from GLPI
                user_info = await self._get_glpi_user_info(client, session_token)

                # Kill the user session (we only needed it for validation)
                await self._kill_glpi_session(client, session_token)

                logger.info(
                    "User authenticated successfully",
                    data={"username": username, "user_id": user_info.get("id")},
                )

                return user_info

            except httpx.HTTPStatusError as e:
                logger.error(
                    "GLPI HTTP error during authentication",
                    data={"status": e.response.status_code},
                )
                raise AuthError("Unable to connect to authentication service")
            except httpx.RequestError as e:
                logger.error(f"GLPI connection error during auth: {e}")
                raise AuthError("Unable to reach authentication service")

    async def _get_glpi_user_info(
        self, client: httpx.AsyncClient, session_token: str
    ) -> Dict[str, Any]:
        """Get the authenticated user's profile from GLPI."""
        try:
            response = await client.get(
                f"{self._glpi_base_url}/apirest.php/getFullSession",
                headers={
                    "Content-Type": "application/json",
                    "App-Token": self._glpi_app_token,
                    "Session-Token": session_token,
                },
            )
            response.raise_for_status()
            data = response.json()

            session_info = data.get("session", {})
            return {
                "id": str(session_info.get("glpiID", "")),
                "username": session_info.get("glpiname", ""),
                "email": session_info.get("glpiemail", ""),
                "firstname": session_info.get("glpifirstname", ""),
                "lastname": session_info.get("glpirealname", ""),
            }
        except Exception as e:
            logger.warning(f"Could not get GLPI user info: {e}")
            return {"id": "", "username": "", "email": ""}

    async def _kill_glpi_session(
        self, client: httpx.AsyncClient, session_token: str
    ) -> None:
        """Kill a GLPI session after validation."""
        try:
            await client.get(
                f"{self._glpi_base_url}/apirest.php/killSession",
                headers={
                    "Content-Type": "application/json",
                    "App-Token": self._glpi_app_token,
                    "Session-Token": session_token,
                },
            )
        except Exception:
            pass  # Non-critical, session will expire on its own

    def create_token(self, user_info: Dict[str, Any]) -> str:
        """
        Create a JWT token for an authenticated user.

        Args:
            user_info: User information from GLPI

        Returns:
            Encoded JWT token string
        """
        now = datetime.utcnow()
        payload = {
            "sub": user_info.get("id", ""),
            "username": user_info.get("username", ""),
            "email": user_info.get("email", ""),
            "iat": now,
            "exp": now + timedelta(minutes=self._token_expiry),
            "iss": "helpdesk-ai",
        }

        token = jwt.encode(payload, self._jwt_secret, algorithm="HS256")
        return token

    def validate_token(self, token: str) -> TokenPayload:
        """
        Validate a JWT token and return the payload.

        Args:
            token: JWT token string

        Returns:
            TokenPayload with user information

        Raises:
            AuthError: If token is invalid or expired
        """
        try:
            allowed_issuers = self.settings.auth.jwt_issuers_list or ["helpdesk-ai"]

            payload = jwt.decode(
                token,
                self._jwt_secret,
                algorithms=["HS256"],
                options={"require": ["sub", "exp", "iss"]},
            )

            # Validate issuer manually (PyJWT 2.x issuer param doesn't accept lists)
            token_issuer = payload.get("iss")
            if token_issuer not in allowed_issuers:
                raise jwt.InvalidIssuerError("Invalid issuer")

            return TokenPayload(
                user_id=payload["sub"],
                username=payload.get("username", ""),
                email=payload.get("email"),
                exp=datetime.utcfromtimestamp(payload["exp"]),
            )

        except jwt.ExpiredSignatureError:
            raise AuthError("Token has expired")
        except jwt.InvalidIssuerError:
            raise AuthError("Invalid token issuer")
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid JWT token: {e}")
            raise AuthError("Invalid authentication token")
