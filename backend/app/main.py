"""
Main application entry point for Helpdesk AI Backend.
"""
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Load environment variables before importing config
from dotenv import load_dotenv
load_dotenv()

from app.core.config import get_settings
from app.core.logging import setup_logging, get_logger
from app.api.routes import router, init_services
from app.api.middleware import (
    RateLimitMiddleware,
    CorrelationIdMiddleware,
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
)
from app.services.glpi_client import GLPIClient
from app.services.cache import get_cache, close_cache
from app.services.session import SessionService


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    logger = get_logger(__name__)

    # Startup
    logger.info("Starting Helpdesk AI Backend...")

    # Initialize cache
    cache = await get_cache()
    logger.info(f"Cache initialized: {'connected' if cache.is_connected else 'disconnected'}")

    # Initialize GLPI client
    glpi_client = GLPIClient(cache=cache if cache.is_connected else None)

    # Test GLPI connection
    try:
        if await glpi_client.test_connection():
            logger.info("GLPI connection successful")
        else:
            logger.warning("GLPI connection test failed - some features may not work")
    except Exception as e:
        logger.error(f"GLPI connection error: {e}")

    # Initialize session service
    session_service = SessionService(cache=cache if cache.is_connected else None)

    # Initialize route services
    init_services(glpi_client, session_service)

    logger.info("Helpdesk AI Backend started successfully")

    yield

    # Shutdown
    logger.info("Shutting down Helpdesk AI Backend...")

    await glpi_client.close()
    await close_cache()

    logger.info("Helpdesk AI Backend shutdown complete")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    # Setup logging
    setup_logging(settings.app.log_level)
    logger = get_logger(__name__)

    # Create app
    app = FastAPI(
        title="Helpdesk AI API",
        description="AI-powered helpdesk chat API integrated with GLPI",
        version="1.0.0",
        docs_url="/docs" if not settings.app.is_production else None,
        redoc_url="/redoc" if not settings.app.is_production else None,
        lifespan=lifespan,
    )

    # Add middleware (order matters - first added = last executed)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(
        RateLimitMiddleware,
        requests_per_minute=settings.app.rate_limit_rpm
    )
    app.add_middleware(CorrelationIdMiddleware)

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.app.allowed_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=[
            "Content-Type",
            "Authorization",
            "X-Correlation-ID",
        ],
        expose_headers=[
            "X-Correlation-ID",
            "X-Response-Time",
        ],
    )

    # Include routers
    app.include_router(router)

    logger.info(
        "Application configured",
        data={
            "env": settings.app.env,
            "cors_origins": settings.app.allowed_origins_list,
            "rate_limit_rpm": settings.app.rate_limit_rpm,
        }
    )

    return app


# Create application instance
app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.app.port,
        reload=not settings.app.is_production,
        log_level=settings.app.log_level,
    )
