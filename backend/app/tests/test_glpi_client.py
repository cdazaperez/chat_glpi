"""
Tests for GLPI client.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from app.services.glpi_client import (
    GLPIClient,
    GLPIError,
    GLPIAuthError,
    GLPINotFoundError,
    GLPIRateLimitError,
)
from app.models.schemas import GLPIKBArticle, GLPITicket, GLPISolution


class TestGLPIClient:
    """Tests for GLPI client functionality."""

    @pytest.fixture
    def client(self, mock_cache):
        """Create a GLPI client with mocked dependencies."""
        with patch("app.services.glpi_client.get_settings") as mock_settings:
            mock_settings.return_value.glpi.base_url = "https://test-glpi.example.com"
            mock_settings.return_value.glpi.app_token = "test-token"
            mock_settings.return_value.glpi.username = "test-user"
            mock_settings.return_value.glpi.password = "test-pass"
            mock_settings.return_value.glpi.timeout_seconds = 30
            mock_settings.return_value.glpi.max_retries = 3
            mock_settings.return_value.glpi.session_timeout_minutes = 30
            mock_settings.return_value.redis.kb_cache_ttl = 3600
            mock_settings.return_value.redis.ticket_cache_ttl = 900

            return GLPIClient(cache=mock_cache)

    def test_client_initialization(self, client):
        """Test client initializes with correct settings."""
        assert client.base_url == "https://test-glpi.example.com"
        assert client.app_token == "test-token"
        assert client._session_token is None

    def test_get_headers_without_session(self, client):
        """Test headers without session token."""
        headers = client._get_headers(include_session=False)

        assert "App-Token" in headers
        assert headers["App-Token"] == "test-token"
        assert "Session-Token" not in headers

    def test_get_headers_with_session(self, client):
        """Test headers with session token."""
        client._session_token = "session-123"
        headers = client._get_headers(include_session=True)

        assert "Session-Token" in headers
        assert headers["Session-Token"] == "session-123"

    def test_cache_key_generation(self, client):
        """Test cache key generation."""
        key1 = client._cache_key("kb_search", {"q": "test"})
        key2 = client._cache_key("kb_search", {"q": "test"})
        key3 = client._cache_key("kb_search", {"q": "different"})

        assert key1 == key2
        assert key1 != key3
        assert key1.startswith("glpi:kb_search:")

    @pytest.mark.asyncio
    async def test_search_kb_returns_cached(self, client, mock_cache):
        """Test that cached KB results are returned."""
        cached_data = [
            {"id": 1, "name": "Test Article", "answer": "Content", "is_faq": False, "view_count": 10}
        ]
        mock_cache.get = AsyncMock(return_value=cached_data)
        client._cache = mock_cache

        results = await client.search_kb("test query")

        assert len(results) == 1
        assert results[0].id == 1
        assert results[0].name == "Test Article"

    @pytest.mark.asyncio
    async def test_search_kb_empty_results(self, client):
        """Test KB search with no results."""
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {"data": []}

            results = await client.search_kb("nonexistent query")

            assert results == []

    @pytest.mark.asyncio
    async def test_get_kb_article_not_found(self, client):
        """Test getting non-existent KB article."""
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = GLPINotFoundError("Not found")

            result = await client.get_kb_article(99999)

            assert result is None

    @pytest.mark.asyncio
    async def test_search_tickets_with_status_filter(self, client):
        """Test ticket search with status filter."""
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {
                "data": [
                    {"1": 100, "2": "Test Ticket", "12": 5}
                ]
            }

            results = await client.search_tickets("test", status="solved")

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert "criteria[1][value]" in call_args[1]["params"]

    @pytest.mark.asyncio
    async def test_create_ticket_success(self, client):
        """Test successful ticket creation."""
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {"id": 123}

            ticket_id = await client.create_ticket(
                title="Test Ticket",
                description="Test description"
            )

            assert ticket_id == 123

    @pytest.mark.asyncio
    async def test_create_ticket_failure(self, client):
        """Test ticket creation failure."""
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = GLPIError("Creation failed")

            with pytest.raises(GLPIError):
                await client.create_ticket(
                    title="Test Ticket",
                    description="Test description"
                )

    @pytest.mark.asyncio
    async def test_test_connection_success(self, client):
        """Test successful connection test."""
        with patch.object(client, "_ensure_session", new_callable=AsyncMock):
            result = await client.test_connection()
            assert result is True

    @pytest.mark.asyncio
    async def test_test_connection_failure(self, client):
        """Test failed connection test."""
        with patch.object(client, "_ensure_session", new_callable=AsyncMock) as mock:
            mock.side_effect = GLPIAuthError("Auth failed")

            result = await client.test_connection()
            assert result is False


class TestGLPIClientErrorHandling:
    """Tests for GLPI client error handling."""

    @pytest.fixture
    def client(self, mock_cache):
        """Create a GLPI client for testing."""
        with patch("app.services.glpi_client.get_settings") as mock_settings:
            mock_settings.return_value.glpi.base_url = "https://test-glpi.example.com"
            mock_settings.return_value.glpi.app_token = "test-token"
            mock_settings.return_value.glpi.username = "test-user"
            mock_settings.return_value.glpi.password = "test-pass"
            mock_settings.return_value.glpi.timeout_seconds = 30
            mock_settings.return_value.glpi.max_retries = 3
            mock_settings.return_value.glpi.session_timeout_minutes = 30
            mock_settings.return_value.redis.kb_cache_ttl = 3600
            mock_settings.return_value.redis.ticket_cache_ttl = 900

            return GLPIClient(cache=mock_cache)

    def test_status_names(self, client):
        """Test status name mapping."""
        assert client.STATUS_NAMES[1] == "New"
        assert client.STATUS_NAMES[5] == "Solved"
        assert client.STATUS_NAMES[6] == "Closed"

    def test_parse_empty_kb_results(self, client):
        """Test parsing empty KB results."""
        results = client._parse_kb_search_results(None)
        assert results == []

        results = client._parse_kb_search_results({})
        assert results == []

        results = client._parse_kb_search_results({"data": []})
        assert results == []

    def test_parse_empty_ticket_results(self, client):
        """Test parsing empty ticket results."""
        results = client._parse_ticket_search_results(None)
        assert results == []

        results = client._parse_ticket_search_results({})
        assert results == []
