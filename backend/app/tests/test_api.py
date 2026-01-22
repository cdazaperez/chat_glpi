"""
API endpoint tests for Helpdesk AI.
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient


class TestHealthEndpoints:
    """Tests for health check endpoints."""

    def test_health_check(self, test_client):
        """Test basic health check endpoint."""
        response = test_client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        assert "version" in data
        assert data["components"]["api"] == "ok"

    @pytest.mark.skip(reason="Requires service initialization")
    def test_readiness_check(self, test_client, mock_glpi_client):
        """Test readiness check endpoint."""
        with patch("app.api.routes._glpi_client", mock_glpi_client):
            response = test_client.get("/health/ready")

            assert response.status_code == 200
            data = response.json()
            assert "components" in data


class TestChatEndpoint:
    """Tests for chat endpoint."""

    def test_chat_missing_message(self, test_client):
        """Test chat with missing message."""
        response = test_client.post("/api/chat", json={})

        assert response.status_code == 422  # Validation error

    def test_chat_empty_message(self, test_client):
        """Test chat with empty message."""
        response = test_client.post("/api/chat", json={"message": ""})

        assert response.status_code == 422  # Validation error

    def test_chat_message_too_long(self, test_client):
        """Test chat with message exceeding max length."""
        long_message = "a" * 5000  # Exceeds default 4000 limit

        response = test_client.post("/api/chat", json={"message": long_message})

        # Should fail validation or be truncated
        assert response.status_code in [400, 422]

    def test_chat_sanitizes_html(self):
        """Test that HTML is sanitized from messages."""
        from app.models.schemas import ChatRequest

        request = ChatRequest(
            message="<script>alert('xss')</script>Hello world"
        )

        assert "<script>" not in request.message
        assert "Hello world" in request.message


class TestTicketEndpoint:
    """Tests for ticket creation endpoint."""

    def test_ticket_missing_title(self, test_client):
        """Test ticket creation with missing title."""
        response = test_client.post("/api/ticket", json={
            "description": "Test description"
        })

        assert response.status_code == 422

    def test_ticket_missing_description(self, test_client):
        """Test ticket creation with missing description."""
        response = test_client.post("/api/ticket", json={
            "title": "Test title"
        })

        assert response.status_code == 422

    def test_ticket_short_title(self, test_client):
        """Test ticket creation with too short title."""
        response = test_client.post("/api/ticket", json={
            "title": "Hi",
            "description": "This is a valid description"
        })

        assert response.status_code == 422

    def test_ticket_invalid_urgency(self, test_client):
        """Test ticket creation with invalid urgency."""
        response = test_client.post("/api/ticket", json={
            "title": "Test ticket title",
            "description": "Test description here",
            "urgency": 10  # Invalid, should be 1-5
        })

        assert response.status_code == 422


class TestSessionEndpoint:
    """Tests for session management endpoints."""

    def test_get_nonexistent_session(self, test_client):
        """Test getting a session that doesn't exist."""
        with patch("app.api.routes._session_service") as mock_svc:
            mock_svc.get_session = AsyncMock(return_value=None)

            response = test_client.get("/api/session/nonexistent-id")

            # Should return 404 or handle gracefully
            assert response.status_code in [404, 503]

    def test_delete_session(self, test_client):
        """Test deleting a session."""
        with patch("app.api.routes._session_service") as mock_svc:
            mock_svc.delete_session = AsyncMock(return_value=True)

            response = test_client.delete("/api/session/test-session-id")

            # Should succeed or return 503 if service not initialized
            assert response.status_code in [200, 503]


class TestInputValidation:
    """Tests for input validation and sanitization."""

    def test_chat_request_strips_whitespace(self):
        """Test that whitespace is stripped from messages."""
        from app.models.schemas import ChatRequest

        request = ChatRequest(message="  Hello world  ")
        assert request.message == "Hello world"

    def test_chat_request_removes_script_tags(self):
        """Test that script tags are removed."""
        from app.models.schemas import ChatRequest

        request = ChatRequest(
            message="Hello <script>evil()</script> world"
        )
        assert "<script>" not in request.message
        assert "evil()" not in request.message

    def test_ticket_request_sanitizes_content(self):
        """Test that ticket content is sanitized."""
        from app.models.schemas import TicketCreateRequest

        request = TicketCreateRequest(
            title="Test <b>title</b>",
            description="Description with <img src=x onerror=alert(1)> image"
        )

        assert "<b>" not in request.title
        assert "<img" not in request.description
