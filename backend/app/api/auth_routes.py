"""
Authentication API routes for Helpdesk AI.
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.auth import AuthService, get_auth_service, AuthResult

logger = get_logger(__name__)

# Create router with prefix
router = APIRouter(prefix="/api/auth", tags=["Authentication"])

# Global auth service instance
_auth_service: Optional[AuthService] = None


def get_auth() -> AuthService:
    """Dependency to get auth service."""
    global _auth_service
    if _auth_service is None:
        _auth_service = get_auth_service()
    return _auth_service


def init_auth_service(auth_service: AuthService):
    """Initialize the auth service instance."""
    global _auth_service
    _auth_service = auth_service


# Request/Response models

class LoginRequest(BaseModel):
    """Login request with GLPI credentials."""
    username: str = Field(..., min_length=1, max_length=100, description="GLPI username")
    password: str = Field(..., min_length=1, max_length=200, description="GLPI password")


class LoginResponse(BaseModel):
    """Login response with JWT tokens."""
    success: bool
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_type: str = "Bearer"
    expires_in: Optional[int] = None
    user: Optional[dict] = None
    error: Optional[str] = None


class RefreshRequest(BaseModel):
    """Token refresh request."""
    refresh_token: str = Field(..., description="Refresh token")


class RefreshResponse(BaseModel):
    """Token refresh response."""
    success: bool
    access_token: Optional[str] = None
    expires_in: Optional[int] = None
    error: Optional[str] = None


class LogoutRequest(BaseModel):
    """Logout request."""
    refresh_token: Optional[str] = Field(None, description="Refresh token to revoke")


class AuthStatusResponse(BaseModel):
    """Authentication status response."""
    enabled: bool
    user: Optional[dict] = None


# Routes

@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, auth_service: AuthService = Depends(get_auth)):
    """
    Authenticate user with GLPI credentials.

    Returns JWT access and refresh tokens if authentication is successful.
    """
    settings = get_settings()

    # Check if auth is enabled
    if not settings.auth.enabled:
        logger.warning("Login attempt when auth is disabled")
        return LoginResponse(
            success=False,
            error="Authentication is not enabled. Contact administrator."
        )

    logger.info("Login attempt", data={"username": request.username})

    result = await auth_service.authenticate(request.username, request.password)

    if not result.success:
        logger.warning("Login failed", data={"username": request.username, "error": result.error})
        raise HTTPException(
            status_code=401,
            detail=result.error or "Authentication failed"
        )

    return LoginResponse(
        success=True,
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        token_type=result.token_type,
        expires_in=result.expires_in,
        user=result.user
    )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh_token(request: RefreshRequest, auth_service: AuthService = Depends(get_auth)):
    """
    Refresh an access token using a refresh token.
    """
    settings = get_settings()

    if not settings.auth.enabled:
        return RefreshResponse(
            success=False,
            error="Authentication is not enabled"
        )

    result = await auth_service.refresh_access_token(request.refresh_token)

    if not result.success:
        raise HTTPException(
            status_code=401,
            detail=result.error or "Token refresh failed"
        )

    return RefreshResponse(
        success=True,
        access_token=result.access_token,
        expires_in=result.expires_in
    )


@router.post("/logout")
async def logout(
    request: Request,
    body: LogoutRequest = None,
    auth_service: AuthService = Depends(get_auth)
):
    """
    Logout user and revoke tokens.
    """
    settings = get_settings()

    if not settings.auth.enabled:
        return {"success": True, "message": "Logged out (auth disabled)"}

    # Revoke access token from header if present
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        access_token = auth_header.split(" ")[1]
        await auth_service.revoke_token(access_token)

    # Revoke refresh token if provided
    if body and body.refresh_token:
        await auth_service.revoke_token(body.refresh_token)

    logger.info("User logged out")
    return {"success": True, "message": "Logged out successfully"}


@router.get("/status", response_model=AuthStatusResponse)
async def auth_status(request: Request):
    """
    Get authentication status and current user info.
    """
    settings = get_settings()

    user_info = None
    if hasattr(request.state, "user") and request.state.user:
        user_info = {
            "id": request.state.user.get("glpi_user_id"),
            "email": request.state.user.get("email"),
            "username": request.state.user.get("username"),
            "name": request.state.user.get("name"),
            "role": request.state.user.get("role"),
        }

    return AuthStatusResponse(
        enabled=settings.auth.enabled,
        user=user_info
    )


@router.get("/config")
async def auth_config():
    """
    Get public authentication configuration.

    This endpoint is used by the frontend to determine how to handle authentication.
    """
    settings = get_settings()

    return {
        "enabled": settings.auth.enabled,
        "token_expiry_minutes": settings.auth.token_expiry_minutes if settings.auth.enabled else None,
    }
