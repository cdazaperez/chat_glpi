"""
API routes for Helpdesk AI.
"""
import time
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Request

from app import __version__
from app.core.config import get_settings
from app.core.logging import get_logger, get_correlation_id
from app.models.schemas import (
    ChatRequest,
    ChatResponse,
    ResponseMetadata,
    TicketCreateRequest,
    TicketCreateResponse,
    HealthStatus,
    ErrorResponse,
    MessageRole,
)
from app.services.glpi_client import GLPIClient, GLPIError
from app.services.llm_orchestrator import LLMOrchestrator, GuardrailViolation
from app.services.session import SessionService
from app.services.cache import get_cache, CacheService

logger = get_logger(__name__)

# Create router
router = APIRouter()

# Global instances (initialized in main.py)
_glpi_client: Optional[GLPIClient] = None
_session_service: Optional[SessionService] = None


def get_glpi_client() -> GLPIClient:
    """Dependency to get GLPI client."""
    if _glpi_client is None:
        raise HTTPException(status_code=503, detail="GLPI client not initialized")
    return _glpi_client


def get_session_service() -> SessionService:
    """Dependency to get session service."""
    if _session_service is None:
        raise HTTPException(status_code=503, detail="Session service not initialized")
    return _session_service


def init_services(glpi_client: GLPIClient, session_service: SessionService):
    """Initialize global service instances."""
    global _glpi_client, _session_service
    _glpi_client = glpi_client
    _session_service = session_service


# Health endpoints

@router.get("/health", response_model=HealthStatus, tags=["Health"])
async def health_check():
    """
    Basic health check endpoint.

    Returns:
        Health status with timestamp
    """
    return HealthStatus(
        status="healthy",
        timestamp=datetime.utcnow(),
        version=__version__,
        components={"api": "ok"}
    )


@router.get("/health/ready", response_model=HealthStatus, tags=["Health"])
async def readiness_check(
    glpi: GLPIClient = Depends(get_glpi_client),
):
    """
    Readiness check - verifies external dependencies.

    Returns:
        Health status with component details
    """
    components = {"api": "ok"}

    # Check GLPI connection
    try:
        glpi_ok = await glpi.test_connection()
        components["glpi"] = "ok" if glpi_ok else "error"
    except Exception:
        components["glpi"] = "error"

    # Check Redis connection
    try:
        cache = await get_cache()
        components["cache"] = "ok" if cache.is_connected else "unavailable"
    except Exception:
        components["cache"] = "unavailable"

    # Determine overall status
    critical_components = ["glpi"]
    status = "healthy"
    for comp in critical_components:
        if components.get(comp) == "error":
            status = "unhealthy"
            break

    return HealthStatus(
        status=status,
        timestamp=datetime.utcnow(),
        version=__version__,
        components=components
    )


# Chat endpoints

@router.post(
    "/api/chat",
    response_model=ChatResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
        503: {"model": ErrorResponse, "description": "Service unavailable"},
    },
    tags=["Chat"],
)
async def chat(
    request: ChatRequest,
    glpi: GLPIClient = Depends(get_glpi_client),
    session_svc: SessionService = Depends(get_session_service),
):
    """
    Process a chat message and return AI response with GLPI references.

    This endpoint:
    1. Validates the message
    2. Searches GLPI knowledge base and tickets
    3. Generates an AI response grounded in GLPI data
    4. Returns response with references and suggested actions
    """
    start_time = time.time()
    correlation_id = get_correlation_id()

    logger.info(
        "Chat request received",
        data={
            "session_id": request.session_id,
            "message_length": len(request.message),
        }
    )

    # Validate message length
    settings = get_settings()
    if len(request.message) > settings.app.max_message_length:
        raise HTTPException(
            status_code=400,
            detail=f"Message too long. Maximum length is {settings.app.max_message_length} characters."
        )

    # Get or create session
    session_id = session_svc.get_or_create_session(
        request.session_id,
        request.context
    )

    try:
        # Get conversation history
        history = await session_svc.get_messages(session_id, limit=10)

        # Add user message to history
        await session_svc.add_message(
            session_id,
            MessageRole.USER,
            request.message
        )

        # Create orchestrator and process message
        orchestrator = LLMOrchestrator(glpi)
        response_text, references, suggested_actions, tokens_used = await orchestrator.process_message(
            request.message,
            history
        )

        # Add assistant response to history
        await session_svc.add_message(
            session_id,
            MessageRole.ASSISTANT,
            response_text,
            references
        )

        # Extend session TTL
        await session_svc.extend_session(session_id)

        # Build response
        processing_time = int((time.time() - start_time) * 1000)

        return ChatResponse(
            response=response_text,
            session_id=session_id,
            references=references,
            suggested_actions=suggested_actions,
            metadata=ResponseMetadata(
                correlation_id=correlation_id,
                processing_time_ms=processing_time,
                sources_consulted=orchestrator.sources_consulted,
                tokens_used=tokens_used,
                cache_hit=orchestrator.cache_hit,
            )
        )

    except GuardrailViolation as e:
        logger.warning("Guardrail violation", data={"error": str(e)})
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )

    except GLPIError as e:
        logger.error("GLPI error in chat", data={"error": str(e)})
        raise HTTPException(
            status_code=503,
            detail="Unable to access knowledge base. Please try again."
        )

    except Exception as e:
        logger.error(f"Error processing chat: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="An error occurred processing your request. Please try again."
        )


@router.post(
    "/api/ticket",
    response_model=TicketCreateResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        503: {"model": ErrorResponse, "description": "Service unavailable"},
    },
    tags=["Tickets"],
)
async def create_ticket(
    request: TicketCreateRequest,
    glpi: GLPIClient = Depends(get_glpi_client),
    session_svc: SessionService = Depends(get_session_service),
):
    """
    Create a new support ticket in GLPI.

    This endpoint creates a ticket with the provided information.
    Use only when the user explicitly requests ticket creation.
    """
    logger.info("Ticket creation requested", data={"title": request.title})

    try:
        ticket_id = await glpi.create_ticket(
            title=request.title,
            description=request.description,
            requester_email=request.requester_email,
            category_id=request.category_id,
            urgency=request.urgency or 3,
            impact=request.impact or 3,
        )

        if ticket_id:
            settings = get_settings()
            ticket_url = f"{settings.glpi.base_url}/front/ticket.form.php?id={ticket_id}"

            logger.info("Ticket created", data={"ticket_id": ticket_id})

            return TicketCreateResponse(
                success=True,
                ticket_id=ticket_id,
                ticket_url=ticket_url,
                message=f"Ticket #{ticket_id} created successfully."
            )
        else:
            return TicketCreateResponse(
                success=False,
                message="Failed to create ticket. Please contact support directly."
            )

    except GLPIError as e:
        logger.error("GLPI error creating ticket", data={"error": str(e)})
        raise HTTPException(
            status_code=503,
            detail="Unable to create ticket. Please try again or contact support directly."
        )

    except Exception as e:
        logger.error(f"Error creating ticket: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="An error occurred creating your ticket. Please try again."
        )


@router.get(
    "/api/session/{session_id}",
    tags=["Session"],
    responses={
        404: {"model": ErrorResponse, "description": "Session not found"},
    },
)
async def get_session(
    session_id: str,
    session_svc: SessionService = Depends(get_session_service),
):
    """
    Get session history by ID.

    Returns the conversation history for the specified session.
    """
    history = await session_svc.get_session(session_id)

    if not history:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "session_id": session_id,
        "messages": [
            {
                "role": msg.role.value,
                "content": msg.content,
                "timestamp": msg.timestamp.isoformat(),
                "references": [ref.model_dump() for ref in msg.references]
            }
            for msg in history.messages
        ],
        "created_at": history.created_at.isoformat(),
        "updated_at": history.updated_at.isoformat(),
    }


@router.delete(
    "/api/session/{session_id}",
    tags=["Session"],
)
async def delete_session(
    session_id: str,
    session_svc: SessionService = Depends(get_session_service),
):
    """
    Delete a session and its history.
    """
    await session_svc.delete_session(session_id)

    return {"message": "Session deleted"}
