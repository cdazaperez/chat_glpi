"""
Pytest configuration and fixtures for Helpdesk AI tests.
"""
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Generator, AsyncGenerator

# Set test environment variables before importing app modules
os.environ.setdefault("GLPI_BASE_URL", "https://test-glpi.example.com")
os.environ.setdefault("GLPI_APP_TOKEN", "test-app-token")
os.environ.setdefault("GLPI_USERNAME", "test-user")
os.environ.setdefault("GLPI_PASSWORD", "test-password")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-key-12345")
os.environ.setdefault("OPENAI_MODEL", "gpt-4.1-mini")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")

from httpx import AsyncClient
from fastapi.testclient import TestClient

from app.main import app
from app.services.glpi_client import GLPIClient
from app.services.cache import CacheService
from app.services.session import SessionService
from app.models.schemas import GLPIKBArticle, GLPITicket, GLPISolution


@pytest.fixture
def test_client() -> Generator:
    """Create a test client for the FastAPI app."""
    with TestClient(app) as client:
        yield client


@pytest.fixture
async def async_client() -> AsyncGenerator:
    """Create an async test client."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client


@pytest.fixture
def mock_cache() -> MagicMock:
    """Create a mock cache service."""
    cache = MagicMock(spec=CacheService)
    cache.is_connected = True
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock(return_value=True)
    cache.delete = AsyncMock(return_value=True)
    cache.get_session = AsyncMock(return_value=None)
    cache.set_session = AsyncMock(return_value=True)
    cache.extend_session = AsyncMock(return_value=True)
    return cache


@pytest.fixture
def mock_glpi_client(mock_cache) -> MagicMock:
    """Create a mock GLPI client."""
    client = MagicMock(spec=GLPIClient)
    client._cache = mock_cache
    client.test_connection = AsyncMock(return_value=True)
    client.close = AsyncMock()

    # Mock KB methods
    client.search_kb = AsyncMock(return_value=[
        GLPIKBArticle(
            id=1,
            name="How to reset your password",
            answer="<p>To reset your password, follow these steps...</p>",
            category_id=1,
            is_faq=True,
            view_count=100,
        ),
        GLPIKBArticle(
            id=2,
            name="VPN Connection Guide",
            answer="<p>To connect to the VPN...</p>",
            category_id=2,
            is_faq=False,
            view_count=50,
        ),
    ])

    client.get_kb_article = AsyncMock(return_value=GLPIKBArticle(
        id=1,
        name="How to reset your password",
        answer="<p>To reset your password, follow these steps:\n1. Go to the login page\n2. Click 'Forgot Password'\n3. Enter your email\n4. Check your inbox</p>",
        category_id=1,
        is_faq=True,
        view_count=100,
    ))

    # Mock ticket methods
    client.search_tickets = AsyncMock(return_value=[
        GLPITicket(
            id=100,
            name="Password reset not working",
            content="User cannot reset password via email",
            status=5,  # Solved
            status_name="Solved",
            urgency=3,
            impact=2,
        ),
        GLPITicket(
            id=101,
            name="Email sync issues",
            content="Outlook not syncing with server",
            status=6,  # Closed
            status_name="Closed",
            urgency=4,
            impact=3,
        ),
    ])

    client.get_ticket = AsyncMock(return_value=GLPITicket(
        id=100,
        name="Password reset not working",
        content="User cannot reset password via email. Error message: 'Invalid token'",
        status=5,
        status_name="Solved",
        urgency=3,
        impact=2,
    ))

    client.get_ticket_solution = AsyncMock(return_value=GLPISolution(
        id=1,
        ticket_id=100,
        content="Cleared the password reset token cache and regenerated tokens. Issue resolved.",
        status=2,
    ))

    client.create_ticket = AsyncMock(return_value=123)

    return client


@pytest.fixture
def mock_openai_response():
    """Create a mock OpenAI response."""
    response = MagicMock()
    response.choices = [
        MagicMock(
            message=MagicMock(
                content="Based on KB #1, here's how to reset your password:\n\n1. Go to the login page\n2. Click 'Forgot Password'\n3. Enter your email\n4. Check your inbox for the reset link",
                tool_calls=None,
            )
        )
    ]
    response.usage = MagicMock(total_tokens=150)
    return response


@pytest.fixture
def mock_openai_tool_call_response():
    """Create a mock OpenAI response with tool calls."""
    tool_call = MagicMock()
    tool_call.id = "call_123"
    tool_call.function.name = "glpi_kb_search"
    tool_call.function.arguments = '{"query": "password reset"}'

    response = MagicMock()
    response.choices = [
        MagicMock(
            message=MagicMock(
                content=None,
                tool_calls=[tool_call],
            )
        )
    ]
    response.usage = MagicMock(total_tokens=50)
    return response


@pytest.fixture
def session_service(mock_cache) -> SessionService:
    """Create a session service with mock cache."""
    return SessionService(cache=mock_cache)


@pytest.fixture
def sample_chat_request():
    """Sample chat request data."""
    return {
        "message": "How do I reset my password?",
        "session_id": None,
        "context": {
            "user_email": "test@example.com",
            "department": "IT"
        }
    }


@pytest.fixture
def sample_ticket_request():
    """Sample ticket creation request."""
    return {
        "title": "Cannot access email",
        "description": "I am unable to access my email since this morning. Getting error 'Connection refused'.",
        "requester_email": "user@example.com",
        "urgency": 3,
        "impact": 2,
    }
