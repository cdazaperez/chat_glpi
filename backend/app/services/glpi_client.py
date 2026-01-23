"""
GLPI API Client with session management, retries, and caching.
"""
import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.schemas import (
    GLPIKBArticle,
    GLPITicket,
    GLPISolution,
    GLPIFollowup,
)

logger = get_logger(__name__)


class GLPIError(Exception):
    """Base exception for GLPI errors."""
    pass


class GLPIAuthError(GLPIError):
    """Authentication error with GLPI."""
    pass


class GLPINotFoundError(GLPIError):
    """Resource not found in GLPI."""
    pass


class GLPIRateLimitError(GLPIError):
    """Rate limit exceeded in GLPI."""
    pass


class GLPIClient:
    """
    Client for interacting with GLPI REST API.

    Features:
    - Session management with automatic refresh
    - Retry logic with exponential backoff
    - Response caching (when cache is provided)
    - Error handling and logging
    """

    # GLPI ticket statuses
    STATUS_NEW = 1
    STATUS_ASSIGNED = 2
    STATUS_PLANNED = 3
    STATUS_PENDING = 4
    STATUS_SOLVED = 5
    STATUS_CLOSED = 6

    STATUS_NAMES = {
        1: "New",
        2: "Assigned",
        3: "Planned",
        4: "Pending",
        5: "Solved",
        6: "Closed",
    }

    def __init__(self, cache=None):
        """Initialize GLPI client."""
        self.settings = get_settings().glpi
        self.base_url = self.settings.base_url
        self.app_token = self.settings.app_token
        self.username = self.settings.username
        self.password = self.settings.password
        self.timeout = self.settings.timeout_seconds
        self.max_retries = self.settings.max_retries

        self._session_token: Optional[str] = None
        self._session_expires: Optional[datetime] = None
        self._cache = cache
        self._cache_hits: int = 0

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout),
            follow_redirects=True,
        )

    async def close(self):
        """Close the HTTP client."""
        if self._session_token:
            try:
                await self._kill_session()
            except Exception as e:
                logger.warning(f"Error killing GLPI session: {e}")
        await self._client.aclose()

    def _get_headers(self, include_session: bool = True) -> Dict[str, str]:
        """Get headers for GLPI API requests."""
        headers = {
            "Content-Type": "application/json",
            "App-Token": self.app_token,
        }
        if include_session and self._session_token:
            headers["Session-Token"] = self._session_token
        return headers

    async def _ensure_session(self):
        """Ensure we have a valid session token."""
        if self._session_token and self._session_expires:
            if datetime.utcnow() < self._session_expires:
                return

        await self._init_session()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
    )
    async def _init_session(self):
        """Initialize a new GLPI session."""
        logger.info("Initializing GLPI session")

        try:
            response = await self._client.get(
                f"{self.base_url}/apirest.php/initSession",
                headers=self._get_headers(include_session=False),
                auth=(self.username, self.password),
            )

            if response.status_code == 401:
                raise GLPIAuthError("Invalid GLPI credentials")

            if response.status_code == 400:
                error_data = response.json()
                raise GLPIAuthError(f"GLPI auth error: {error_data}")

            response.raise_for_status()
            data = response.json()

            self._session_token = data.get("session_token")
            self._session_expires = datetime.utcnow() + timedelta(
                minutes=self.settings.session_timeout_minutes - 5
            )

            logger.info("GLPI session initialized successfully")

        except httpx.HTTPStatusError as e:
            logger.error(f"GLPI session init failed: {e.response.status_code}")
            raise GLPIError(f"Failed to initialize GLPI session: {e}")

    async def _kill_session(self):
        """Kill the current GLPI session."""
        if not self._session_token:
            return

        try:
            await self._client.get(
                f"{self.base_url}/apirest.php/killSession",
                headers=self._get_headers(),
            )
            self._session_token = None
            self._session_expires = None
            logger.info("GLPI session killed")
        except Exception as e:
            logger.warning(f"Error killing GLPI session: {e}")

    def _cache_key(self, prefix: str, params: Dict[str, Any]) -> str:
        """Generate a cache key from parameters."""
        param_str = json.dumps(params, sort_keys=True)
        hash_val = hashlib.md5(param_str.encode()).hexdigest()
        return f"glpi:{prefix}:{hash_val}"

    async def _get_cached(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        if not self._cache:
            return None
        try:
            result = await self._cache.get(key)
            if result is not None:
                self._cache_hits += 1
            return result
        except Exception as e:
            logger.warning(f"Cache get error: {e}")
            return None

    @property
    def cache_hits(self) -> int:
        """Get the number of cache hits since last reset."""
        return self._cache_hits

    def reset_cache_hits(self):
        """Reset the cache hits counter."""
        self._cache_hits = 0

    async def _set_cached(self, key: str, value: Any, ttl: int):
        """Set value in cache."""
        if not self._cache:
            return
        try:
            await self._cache.set(key, value, ttl)
        except Exception as e:
            logger.warning(f"Cache set error: {e}")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
    )
    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Make an authenticated request to GLPI API."""
        await self._ensure_session()

        url = f"{self.base_url}/apirest.php/{endpoint}"

        try:
            response = await self._client.request(
                method,
                url,
                headers=self._get_headers(),
                params=params,
                json=json_data,
            )

            if response.status_code == 401:
                # Session expired, retry with new session
                self._session_token = None
                await self._ensure_session()
                response = await self._client.request(
                    method,
                    url,
                    headers=self._get_headers(),
                    params=params,
                    json=json_data,
                )

            if response.status_code == 404:
                raise GLPINotFoundError(f"Resource not found: {endpoint}")

            if response.status_code == 429:
                raise GLPIRateLimitError("GLPI rate limit exceeded")

            response.raise_for_status()

            if response.content:
                return response.json()
            return None

        except httpx.HTTPStatusError as e:
            logger.error(
                f"GLPI request failed",
                data={
                    "endpoint": endpoint,
                    "status": e.response.status_code,
                    "method": method,
                }
            )
            raise GLPIError(f"GLPI request failed: {e.response.status_code}")

    # Knowledge Base Methods

    async def search_kb(
        self,
        query: str,
        category_id: Optional[int] = None,
        limit: int = 5,
    ) -> List[GLPIKBArticle]:
        """
        Search Knowledge Base articles.

        Args:
            query: Search query
            category_id: Optional category filter
            limit: Maximum results to return

        Returns:
            List of matching KB articles
        """
        cache_key = self._cache_key("kb_search", {"q": query, "cat": category_id, "limit": limit})
        cached = await self._get_cached(cache_key)
        if cached:
            logger.debug("KB search cache hit", data={"query": query})
            return [GLPIKBArticle(**item) for item in cached]

        logger.info("Searching GLPI KB", data={"query": query, "category_id": category_id})

        # Build search criteria
        criteria = [
            {
                "field": "view",  # Search in searchable fields
                "searchtype": "contains",
                "value": query,
            }
        ]

        if category_id:
            criteria.append({
                "link": "AND",
                "field": 3,  # Category field
                "searchtype": "equals",
                "value": category_id,
            })

        params = {
            "criteria[0][field]": "view",
            "criteria[0][searchtype]": "contains",
            "criteria[0][value]": query,
            "forcedisplay[0]": 2,  # Name
            "forcedisplay[1]": 4,  # Answer
            "forcedisplay[2]": 3,  # Category
            "range": f"0-{limit - 1}",
            "sort": 9,  # Sort by view count
            "order": "DESC",
        }

        if category_id:
            params["criteria[1][link]"] = "AND"
            params["criteria[1][field]"] = 3
            params["criteria[1][searchtype]"] = "equals"
            params["criteria[1][value]"] = category_id

        try:
            result = await self._request("GET", "search/KnowbaseItem", params=params)
            articles = self._parse_kb_search_results(result)

            # Cache results
            await self._set_cached(
                cache_key,
                [a.model_dump() for a in articles],
                get_settings().redis.kb_cache_ttl,
            )

            return articles

        except GLPINotFoundError:
            return []
        except Exception as e:
            logger.error(f"KB search failed: {e}")
            raise

    def _parse_kb_search_results(self, result: Any) -> List[GLPIKBArticle]:
        """Parse GLPI search results into KB articles."""
        if not result or "data" not in result:
            return []

        articles = []
        for item in result.get("data", []):
            try:
                article = GLPIKBArticle(
                    id=item.get("2") or item.get("id", 0),
                    name=item.get("2") if isinstance(item.get("2"), str) else item.get("1", ""),
                    answer=item.get("4") or item.get("answer"),
                    category_id=item.get("3"),
                    is_faq=bool(item.get("is_faq", False)),
                    view_count=item.get("9", 0),
                )
                articles.append(article)
            except Exception as e:
                logger.warning(f"Error parsing KB article: {e}")
                continue

        return articles

    async def get_kb_article(self, kb_id: int) -> Optional[GLPIKBArticle]:
        """
        Get a specific Knowledge Base article by ID.

        Args:
            kb_id: The KB article ID

        Returns:
            The KB article or None if not found
        """
        cache_key = f"glpi:kb_item:{kb_id}"
        cached = await self._get_cached(cache_key)
        if cached:
            return GLPIKBArticle(**cached)

        logger.info("Getting GLPI KB article", data={"kb_id": kb_id})

        try:
            result = await self._request("GET", f"KnowbaseItem/{kb_id}")

            if not result:
                return None

            article = GLPIKBArticle(
                id=result.get("id"),
                name=result.get("name", ""),
                answer=result.get("answer", ""),
                category_id=result.get("knowbaseitemcategories_id"),
                is_faq=bool(result.get("is_faq", False)),
                view_count=result.get("view", 0),
                date_creation=result.get("date_creation"),
                date_mod=result.get("date_mod"),
            )

            await self._set_cached(
                cache_key,
                article.model_dump(),
                get_settings().redis.kb_cache_ttl,
            )

            return article

        except GLPINotFoundError:
            return None

    # Ticket Methods

    async def search_tickets(
        self,
        query: str,
        status: Optional[str] = "solved",
        category_id: Optional[int] = None,
        limit: int = 5,
    ) -> List[GLPITicket]:
        """
        Search tickets in GLPI.

        Args:
            query: Search query
            status: Filter by status ('solved', 'closed', 'all')
            category_id: Optional category filter
            limit: Maximum results to return

        Returns:
            List of matching tickets
        """
        cache_key = self._cache_key(
            "ticket_search",
            {"q": query, "status": status, "cat": category_id, "limit": limit}
        )
        cached = await self._get_cached(cache_key)
        if cached:
            logger.debug("Ticket search cache hit", data={"query": query})
            return [GLPITicket(**item) for item in cached]

        logger.info(
            "Searching GLPI tickets",
            data={"query": query, "status": status, "category_id": category_id}
        )

        # Build search parameters
        params = {
            "forcedisplay[0]": 1,   # ID
            "forcedisplay[1]": 2,   # Name
            "forcedisplay[2]": 21,  # Content
            "forcedisplay[3]": 12,  # Status
            "forcedisplay[4]": 10,  # Urgency
            "forcedisplay[5]": 11,  # Impact
            "forcedisplay[6]": 7,   # Category
            "range": f"0-{limit - 1}",
            "sort": 19,  # Sort by modification date
            "order": "DESC",
        }

        criteria_idx = 0

        # Add text search criteria only if query is not empty
        if query and query.strip():
            # Search in ticket name (field 1)
            params[f"criteria[{criteria_idx}][field]"] = 1
            params[f"criteria[{criteria_idx}][searchtype]"] = "contains"
            params[f"criteria[{criteria_idx}][value]"] = query.strip()
            criteria_idx += 1
            # Also search in content (field 21) with OR
            params[f"criteria[{criteria_idx}][link]"] = "OR"
            params[f"criteria[{criteria_idx}][field]"] = 21
            params[f"criteria[{criteria_idx}][searchtype]"] = "contains"
            params[f"criteria[{criteria_idx}][value]"] = query.strip()
            criteria_idx += 1

        # Add status filter
        if status == "solved":
            if criteria_idx > 0:
                params[f"criteria[{criteria_idx}][link]"] = "AND"
            params[f"criteria[{criteria_idx}][field]"] = 12
            params[f"criteria[{criteria_idx}][searchtype]"] = "equals"
            params[f"criteria[{criteria_idx}][value]"] = self.STATUS_SOLVED
            criteria_idx += 1
        elif status == "closed":
            if criteria_idx > 0:
                params[f"criteria[{criteria_idx}][link]"] = "AND"
            params[f"criteria[{criteria_idx}][field]"] = 12
            params[f"criteria[{criteria_idx}][searchtype]"] = "equals"
            params[f"criteria[{criteria_idx}][value]"] = self.STATUS_CLOSED
            criteria_idx += 1
        elif status == "resolved":
            # Both solved and closed
            if criteria_idx > 0:
                params[f"criteria[{criteria_idx}][link]"] = "AND"
            params[f"criteria[{criteria_idx}][field]"] = 12
            params[f"criteria[{criteria_idx}][searchtype]"] = "equals"
            params[f"criteria[{criteria_idx}][value]"] = self.STATUS_SOLVED
            criteria_idx += 1
            params[f"criteria[{criteria_idx}][link]"] = "OR"
            params[f"criteria[{criteria_idx}][field]"] = 12
            params[f"criteria[{criteria_idx}][searchtype]"] = "equals"
            params[f"criteria[{criteria_idx}][value]"] = self.STATUS_CLOSED
            criteria_idx += 1

        if category_id:
            if criteria_idx > 0:
                params[f"criteria[{criteria_idx}][link]"] = "AND"
            params[f"criteria[{criteria_idx}][field]"] = 7
            params[f"criteria[{criteria_idx}][searchtype]"] = "equals"
            params[f"criteria[{criteria_idx}][value]"] = category_id

        try:
            result = await self._request("GET", "search/Ticket", params=params)
            tickets = self._parse_ticket_search_results(result)

            # Cache results
            await self._set_cached(
                cache_key,
                [t.model_dump() for t in tickets],
                get_settings().redis.ticket_cache_ttl,
            )

            return tickets

        except GLPINotFoundError:
            return []
        except Exception as e:
            logger.error(f"Ticket search failed: {e}")
            raise

    def _parse_ticket_search_results(self, result: Any) -> List[GLPITicket]:
        """Parse GLPI search results into tickets."""
        if not result or "data" not in result:
            return []

        tickets = []
        for item in result.get("data", []):
            try:
                status_val = item.get("12", 1)
                ticket = GLPITicket(
                    id=item.get("1") or item.get("id", 0),
                    name=item.get("2", ""),
                    content=item.get("21"),
                    status=status_val,
                    status_name=self.STATUS_NAMES.get(status_val),
                    urgency=item.get("10", 3),
                    impact=item.get("11", 3),
                    category_id=item.get("7"),
                )
                tickets.append(ticket)
            except Exception as e:
                logger.warning(f"Error parsing ticket: {e}")
                continue

        return tickets

    async def get_ticket(self, ticket_id: int) -> Optional[GLPITicket]:
        """
        Get a specific ticket by ID.

        Args:
            ticket_id: The ticket ID

        Returns:
            The ticket or None if not found
        """
        cache_key = f"glpi:ticket_item:{ticket_id}"
        cached = await self._get_cached(cache_key)
        if cached:
            return GLPITicket(**cached)

        logger.info("Getting GLPI ticket", data={"ticket_id": ticket_id})

        try:
            result = await self._request("GET", f"Ticket/{ticket_id}")

            if not result:
                return None

            ticket = GLPITicket(
                id=result.get("id"),
                name=result.get("name", ""),
                content=result.get("content"),
                status=result.get("status", 1),
                status_name=self.STATUS_NAMES.get(result.get("status", 1)),
                urgency=result.get("urgency", 3),
                impact=result.get("impact", 3),
                priority=result.get("priority", 3),
                category_id=result.get("itilcategories_id"),
                date_creation=result.get("date_creation"),
                date_mod=result.get("date_mod"),
                solvedate=result.get("solvedate"),
                closedate=result.get("closedate"),
            )

            await self._set_cached(
                cache_key,
                ticket.model_dump(),
                get_settings().redis.ticket_cache_ttl,
            )

            return ticket

        except GLPINotFoundError:
            return None

    async def get_ticket_solution(self, ticket_id: int) -> Optional[GLPISolution]:
        """
        Get the solution for a ticket.

        Args:
            ticket_id: The ticket ID

        Returns:
            The solution or None if not found
        """
        logger.info("Getting GLPI ticket solution", data={"ticket_id": ticket_id})

        try:
            # Get solutions for the ticket
            result = await self._request(
                "GET",
                f"Ticket/{ticket_id}/ITILSolution"
            )

            if not result or len(result) == 0:
                return None

            # Get the most recent solution (usually the accepted one)
            solution_data = result[-1] if isinstance(result, list) else result

            solution = GLPISolution(
                id=solution_data.get("id"),
                ticket_id=ticket_id,
                content=solution_data.get("content", ""),
                status=solution_data.get("status", 0),
                date_creation=solution_data.get("date_creation"),
            )

            return solution

        except GLPINotFoundError:
            return None
        except Exception as e:
            logger.error(f"Error getting ticket solution: {e}")
            return None

    async def get_ticket_followups(
        self,
        ticket_id: int,
        limit: int = 10
    ) -> List[GLPIFollowup]:
        """
        Get followups for a ticket.

        Args:
            ticket_id: The ticket ID
            limit: Maximum followups to return

        Returns:
            List of followups
        """
        logger.info("Getting GLPI ticket followups", data={"ticket_id": ticket_id})

        try:
            result = await self._request(
                "GET",
                f"Ticket/{ticket_id}/ITILFollowup",
                params={"range": f"0-{limit - 1}"}
            )

            if not result:
                return []

            followups = []
            items = result if isinstance(result, list) else [result]

            for item in items:
                if item.get("is_private", False):
                    continue  # Skip private followups

                followup = GLPIFollowup(
                    id=item.get("id"),
                    ticket_id=ticket_id,
                    content=item.get("content", ""),
                    is_private=item.get("is_private", False),
                    date_creation=item.get("date_creation"),
                )
                followups.append(followup)

            return followups

        except GLPINotFoundError:
            return []
        except Exception as e:
            logger.error(f"Error getting ticket followups: {e}")
            return []

    async def create_ticket(
        self,
        title: str,
        description: str,
        requester_email: Optional[str] = None,
        category_id: Optional[int] = None,
        urgency: int = 3,
        impact: int = 3,
    ) -> Optional[int]:
        """
        Create a new ticket in GLPI.

        Args:
            title: Ticket title
            description: Ticket description
            requester_email: Optional requester email
            category_id: Optional category ID
            urgency: Urgency level (1-5)
            impact: Impact level (1-5)

        Returns:
            The new ticket ID or None if creation failed
        """
        logger.info("Creating GLPI ticket", data={"title": title})

        payload = {
            "input": {
                "name": title,
                "content": description,
                "urgency": urgency,
                "impact": impact,
                "status": self.STATUS_NEW,
            }
        }

        if category_id:
            payload["input"]["itilcategories_id"] = category_id

        # Note: requester handling depends on GLPI configuration
        # This may need adjustment based on the specific GLPI setup

        try:
            result = await self._request("POST", "Ticket", json_data=payload)

            if result and "id" in result:
                logger.info("GLPI ticket created", data={"ticket_id": result["id"]})
                return result["id"]

            return None

        except Exception as e:
            logger.error(f"Error creating ticket: {e}")
            raise GLPIError(f"Failed to create ticket: {e}")

    # Utility Methods

    async def test_connection(self) -> bool:
        """Test the GLPI connection."""
        try:
            await self._ensure_session()
            return True
        except Exception as e:
            logger.error(f"GLPI connection test failed: {e}")
            return False
