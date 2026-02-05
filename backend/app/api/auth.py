"""
Authentication dependencies for FastAPI routes.
"""
from typing import Optional

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.auth import AuthService, AuthError, TokenPayload

logger = get_logger(__name__)

# Optional bearer scheme — auto_error=False so unauthenticated requests
# get a clear 401 instead of a generic 403.
_bearer_scheme = HTTPBearer(auto_error=False)

# Module-level auth service instance (lazy init)
_auth_service: Optional[AuthService] = None


def get_auth_service() -> AuthService:
    """Get or create the singleton AuthService."""
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service


async def require_auth(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> TokenPayload:
    """
    FastAPI dependency that enforces authentication.

    When AUTH_ENABLED is True, this validates the JWT token from the
    Authorization header and returns the token payload.

    When AUTH_ENABLED is False, this returns a default anonymous payload
    to allow unauthenticated access (development mode).

    Usage in routes:
        @router.get("/protected")
        async def protected(user: TokenPayload = Depends(require_auth)):
            ...
    """
    settings = get_settings()

    if not settings.auth.enabled:
        # Auth disabled — return anonymous user for backwards compatibility
        return TokenPayload(
            user_id="anonymous",
            username="anonymous",
            email=None,
        )

    # Auth is enabled — token is required
    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Please log in.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        auth_service = get_auth_service()
        payload = auth_service.validate_token(credentials.credentials)
        return payload
    except AuthError as e:
        logger.warning(
            "Authentication failed",
            data={"error": str(e), "path": request.url.path},
        )
        raise HTTPException(
            status_code=401,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )
