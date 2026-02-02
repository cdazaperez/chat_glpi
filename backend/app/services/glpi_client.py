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
    RetryError,
)

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.schemas import (
    GLPIKBArticle,
    GLPITicket,
    GLPISolution,
    GLPIFollowup,
    GLPITask,
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
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=15),
        retry=retry_if_exception_type((
            httpx.TimeoutException,
            httpx.NetworkError,
            httpx.ConnectError,
            httpx.TransportError,
        )),
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
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=15),
        retry=retry_if_exception_type((
            httpx.TimeoutException,
            httpx.NetworkError,
            httpx.ConnectError,
            httpx.TransportError,
        )),
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

            # Handle 400 Bad Request with detailed error message
            if response.status_code == 400:
                error_detail = "Bad request"
                try:
                    error_body = response.json()
                    if isinstance(error_body, list) and len(error_body) > 0:
                        error_detail = str(error_body[0])
                    elif isinstance(error_body, dict):
                        error_detail = error_body.get("message", str(error_body))
                    else:
                        error_detail = str(error_body)
                except Exception:
                    error_detail = response.text[:500] if response.text else "Unknown error"

                logger.error(
                    f"GLPI bad request",
                    data={
                        "endpoint": endpoint,
                        "method": method,
                        "error_detail": error_detail,
                        "payload": json_data,
                    }
                )
                raise GLPIError(f"GLPI bad request: {error_detail}")

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

    async def create_kb_article(
        self,
        name: str,
        content: str,
        category_id: Optional[int] = None,
        is_faq: bool = False,
    ) -> Optional[int]:
        """
        Create a new Knowledge Base article in GLPI.

        Args:
            name: Article title
            content: Article content (can include HTML)
            category_id: Optional category ID
            is_faq: Whether this is a FAQ article

        Returns:
            The new article ID or None if creation failed
        """
        logger.info("Creating GLPI KB article", data={"name": name})

        payload = {
            "input": {
                "name": name,
                "answer": content,
                "is_faq": 1 if is_faq else 0,
            }
        }

        if category_id:
            payload["input"]["knowbaseitemcategories_id"] = category_id

        try:
            result = await self._request("POST", "KnowbaseItem", json_data=payload)

            if result and isinstance(result, dict):
                article_id = result.get("id")
                if article_id:
                    logger.info(
                        "GLPI KB article created",
                        data={"article_id": article_id, "name": name}
                    )
                    return article_id

            # Some GLPI versions return the ID differently
            if result and isinstance(result, list) and len(result) > 0:
                article_id = result[0].get("id") if isinstance(result[0], dict) else result[0]
                if article_id:
                    logger.info(
                        "GLPI KB article created",
                        data={"article_id": article_id, "name": name}
                    )
                    return article_id

            logger.error("Failed to create KB article: unexpected response", data={"result": str(result)})
            return None

        except GLPIError as e:
            logger.error(f"Error creating KB article: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error creating KB article: {e}")
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
        if status == "new":
            if criteria_idx > 0:
                params[f"criteria[{criteria_idx}][link]"] = "AND"
            params[f"criteria[{criteria_idx}][field]"] = 12
            params[f"criteria[{criteria_idx}][searchtype]"] = "equals"
            params[f"criteria[{criteria_idx}][value]"] = self.STATUS_NEW
            criteria_idx += 1
        elif status == "assigned":
            if criteria_idx > 0:
                params[f"criteria[{criteria_idx}][link]"] = "AND"
            params[f"criteria[{criteria_idx}][field]"] = 12
            params[f"criteria[{criteria_idx}][searchtype]"] = "equals"
            params[f"criteria[{criteria_idx}][value]"] = self.STATUS_ASSIGNED
            criteria_idx += 1
        elif status == "pending":
            if criteria_idx > 0:
                params[f"criteria[{criteria_idx}][link]"] = "AND"
            params[f"criteria[{criteria_idx}][field]"] = 12
            params[f"criteria[{criteria_idx}][searchtype]"] = "equals"
            params[f"criteria[{criteria_idx}][value]"] = self.STATUS_PENDING
            criteria_idx += 1
        elif status == "planned":
            if criteria_idx > 0:
                params[f"criteria[{criteria_idx}][link]"] = "AND"
            params[f"criteria[{criteria_idx}][field]"] = 12
            params[f"criteria[{criteria_idx}][searchtype]"] = "equals"
            params[f"criteria[{criteria_idx}][value]"] = self.STATUS_PLANNED
            criteria_idx += 1
        elif status == "open":
            # All tickets without solution: new, assigned, pending, planned
            if criteria_idx > 0:
                params[f"criteria[{criteria_idx}][link]"] = "AND"
            # Use a group to combine with OR
            params[f"criteria[{criteria_idx}][field]"] = 12
            params[f"criteria[{criteria_idx}][searchtype]"] = "equals"
            params[f"criteria[{criteria_idx}][value]"] = self.STATUS_NEW
            criteria_idx += 1
            params[f"criteria[{criteria_idx}][link]"] = "OR"
            params[f"criteria[{criteria_idx}][field]"] = 12
            params[f"criteria[{criteria_idx}][searchtype]"] = "equals"
            params[f"criteria[{criteria_idx}][value]"] = self.STATUS_ASSIGNED
            criteria_idx += 1
            params[f"criteria[{criteria_idx}][link]"] = "OR"
            params[f"criteria[{criteria_idx}][field]"] = 12
            params[f"criteria[{criteria_idx}][searchtype]"] = "equals"
            params[f"criteria[{criteria_idx}][value]"] = self.STATUS_PENDING
            criteria_idx += 1
            params[f"criteria[{criteria_idx}][link]"] = "OR"
            params[f"criteria[{criteria_idx}][field]"] = 12
            params[f"criteria[{criteria_idx}][searchtype]"] = "equals"
            params[f"criteria[{criteria_idx}][value]"] = self.STATUS_PLANNED
            criteria_idx += 1
        elif status == "solved":
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

    async def add_ticket_followup(
        self,
        ticket_id: int,
        content: str,
        is_private: bool = False,
        users_id: Optional[int] = None
    ) -> Optional[int]:
        """
        Add a followup/comment to a ticket.

        Args:
            ticket_id: The ticket ID
            content: The followup content
            is_private: Whether the followup is private
            users_id: Optional user ID to attribute the followup to

        Returns:
            The followup ID or None if creation failed
        """
        logger.info("Adding followup to ticket", data={"ticket_id": ticket_id, "users_id": users_id})

        payload = {
            "input": {
                "items_id": ticket_id,
                "itemtype": "Ticket",
                "content": content,
                "is_private": 1 if is_private else 0,
            }
        }

        # Add user attribution if provided
        if users_id:
            payload["input"]["users_id"] = users_id

        try:
            result = await self._request(
                "POST",
                "ITILFollowup",
                json_data=payload
            )

            if result:
                followup_id = result.get("id") if isinstance(result, dict) else (
                    result[0].get("id") if isinstance(result, list) and result else None
                )
                if followup_id:
                    logger.info("Followup added to ticket", data={"ticket_id": ticket_id, "followup_id": followup_id})
                    return followup_id

            return None

        except GLPIError as e:
            logger.error(f"Error adding followup to ticket: {e}")
            raise
        except RetryError as e:
            logger.error(f"Connection to GLPI failed after retries: {e}")
            raise GLPIError(f"Unable to connect to GLPI server after multiple attempts")
        except Exception as e:
            logger.error(f"Unexpected error adding followup: {e}")
            raise GLPIError(f"Unexpected error adding followup: {e}")

    async def get_ticket_tasks(
        self,
        ticket_id: int,
        limit: int = 10
    ) -> List[GLPITask]:
        """
        Get tasks for a ticket.

        Args:
            ticket_id: The ticket ID
            limit: Maximum tasks to return

        Returns:
            List of tasks
        """
        logger.info("Getting GLPI ticket tasks", data={"ticket_id": ticket_id})

        try:
            result = await self._request(
                "GET",
                f"Ticket/{ticket_id}/TicketTask",
                params={"range": f"0-{limit - 1}"}
            )

            if not result:
                return []

            tasks = []
            items = result if isinstance(result, list) else [result]

            for item in items:
                if item.get("is_private", False):
                    continue  # Skip private tasks

                task = GLPITask(
                    id=item.get("id"),
                    ticket_id=ticket_id,
                    content=item.get("content", ""),
                    state=item.get("state", 1),
                    is_private=item.get("is_private", False),
                    date_creation=item.get("date_creation"),
                    begin_date=item.get("begin"),
                    end_date=item.get("end"),
                )
                tasks.append(task)

            return tasks

        except GLPINotFoundError:
            return []
        except Exception as e:
            logger.error(f"Error getting ticket tasks: {e}")
            return []

    async def add_ticket_task(
        self,
        ticket_id: int,
        content: str,
        state: int = 1,
        is_private: bool = False,
        users_id: Optional[int] = None
    ) -> Optional[int]:
        """
        Add a task to a ticket.

        Args:
            ticket_id: The ticket ID
            content: The task content/description
            state: Task state (0=Information, 1=To do, 2=Done)
            is_private: Whether the task is private
            users_id: Optional user ID to attribute the task to

        Returns:
            The task ID or None if creation failed
        """
        logger.info("Adding task to ticket", data={"ticket_id": ticket_id, "users_id": users_id})

        payload = {
            "input": {
                "tickets_id": ticket_id,
                "content": content,
                "state": state,
                "is_private": 1 if is_private else 0,
            }
        }

        # Add user attribution if provided
        if users_id:
            payload["input"]["users_id"] = users_id

        try:
            result = await self._request(
                "POST",
                "TicketTask",
                json_data=payload
            )

            if result:
                task_id = result.get("id") if isinstance(result, dict) else (
                    result[0].get("id") if isinstance(result, list) and result else None
                )
                if task_id:
                    logger.info("Task added to ticket", data={"ticket_id": ticket_id, "task_id": task_id})
                    return task_id

            return None

        except GLPIError as e:
            logger.error(f"Error adding task to ticket: {e}")
            raise
        except RetryError as e:
            logger.error(f"Connection to GLPI failed after retries: {e}")
            raise GLPIError(f"Unable to connect to GLPI server after multiple attempts")
        except Exception as e:
            logger.error(f"Unexpected error adding task: {e}")
            raise GLPIError(f"Unexpected error adding task: {e}")

    async def add_ticket_solution(
        self,
        ticket_id: int,
        content: str,
        users_id: Optional[int] = None,
        solutiontypes_id: Optional[int] = None
    ) -> Optional[int]:
        """
        Add a solution to a ticket.

        Args:
            ticket_id: The ticket ID
            content: The solution content
            users_id: Optional user ID to attribute the solution to (may not be supported by all GLPI versions)
            solutiontypes_id: Optional solution type ID

        Returns:
            The solution ID or None if creation failed
        """
        logger.info("Adding solution to ticket", data={"ticket_id": ticket_id, "users_id": users_id})

        payload = {
            "input": {
                "items_id": ticket_id,
                "itemtype": "Ticket",
                "content": content,
            }
        }

        # Add solution type if provided
        if solutiontypes_id:
            payload["input"]["solutiontypes_id"] = solutiontypes_id

        # Add user attribution if provided (note: may not be supported in all GLPI versions)
        if users_id:
            payload["input"]["users_id"] = users_id

        try:
            result = await self._request(
                "POST",
                "ITILSolution",
                json_data=payload
            )

            if result:
                solution_id = result.get("id") if isinstance(result, dict) else (
                    result[0].get("id") if isinstance(result, list) and result else None
                )
                if solution_id:
                    logger.info("Solution added to ticket", data={"ticket_id": ticket_id, "solution_id": solution_id})
                    return solution_id

            return None

        except GLPIError as e:
            logger.error(f"Error adding solution to ticket: {e}")
            raise
        except RetryError as e:
            logger.error(f"Connection to GLPI failed after retries: {e}")
            raise GLPIError(f"Unable to connect to GLPI server after multiple attempts")
        except Exception as e:
            logger.error(f"Unexpected error adding solution: {e}")
            raise GLPIError(f"Unexpected error adding solution: {e}")

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

    # User Methods

    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """
        Get a GLPI user by email address or username.

        Searches in order:
        1. By exact email match
        2. By username (part before @) with exact match
        3. By username with 'contains' search

        Args:
            email: The user's email address

        Returns:
            User data dict with id, name, etc. or None if not found
        """
        if not email:
            return None

        cache_key = f"glpi:user_email:{email.lower()}"
        cached = await self._get_cached(cache_key)
        if cached:
            return cached

        logger.info("Looking up GLPI user", data={"email": email})

        # Extract username from email
        username = email.split("@")[0] if "@" in email else email

        # Define search strategies in order of preference
        search_strategies = [
            # Strategy 1: Search by exact email
            {
                "name": "email_exact",
                "field": 5,  # Email field
                "searchtype": "equals",
                "value": email,
            },
            # Strategy 2: Search by exact username (login field)
            {
                "name": "username_exact",
                "field": 1,  # Name/login field
                "searchtype": "equals",
                "value": username,
            },
            # Strategy 3: Search by username contains
            {
                "name": "username_contains",
                "field": 1,  # Name/login field
                "searchtype": "contains",
                "value": username,
            },
            # Strategy 4: Search by email contains username
            {
                "name": "email_contains_username",
                "field": 5,  # Email field
                "searchtype": "contains",
                "value": username,
            },
        ]

        try:
            for strategy in search_strategies:
                params = {
                    "criteria[0][field]": strategy["field"],
                    "criteria[0][searchtype]": strategy["searchtype"],
                    "criteria[0][value]": strategy["value"],
                    "forcedisplay[0]": 2,  # ID
                    "forcedisplay[1]": 34,  # Name (realname)
                    "forcedisplay[2]": 5,  # Email
                    "forcedisplay[3]": 1,  # Username/login
                    "range": "0-0",
                }

                logger.debug(
                    f"Trying search strategy: {strategy['name']}",
                    data={"field": strategy["field"], "value": strategy["value"]}
                )

                result = await self._request("GET", "search/User", params=params)

                logger.debug(
                    f"Search result for {strategy['name']}",
                    data={"has_data": bool(result and "data" in result and len(result.get("data", [])) > 0)}
                )

                if result and "data" in result and len(result["data"]) > 0:
                    user_data = result["data"][0]
                    user = {
                        "id": user_data.get("2") or user_data.get("id"),
                        "name": user_data.get("34", ""),
                        "email": user_data.get("5", email),
                        "username": user_data.get("1", username),
                    }

                    # Cache for 1 hour
                    await self._set_cached(cache_key, user, 3600)
                    logger.info(
                        "GLPI user found",
                        data={
                            "user_id": user["id"],
                            "strategy": strategy["name"],
                            "email": email,
                            "username": username
                        }
                    )
                    return user

            logger.info("GLPI user not found after all strategies", data={"email": email, "username": username})
            return None

        except Exception as e:
            logger.error(f"Error looking up user: {e}", data={"email": email, "username": username})
            return None

    async def get_user_id_by_email(self, email: str) -> Optional[int]:
        """
        Get a GLPI user ID by email address.

        Args:
            email: The user's email address

        Returns:
            User ID or None if not found
        """
        user = await self.get_user_by_email(email)
        return user["id"] if user else None

    async def get_user_profile(self, user_id: int) -> Optional[Dict[str, Any]]:
        """
        Get detailed user profile including role/permissions.

        Args:
            user_id: The GLPI user ID

        Returns:
            User profile dict with id, name, email, role, permissions
        """
        cache_key = f"glpi:user_profile:{user_id}"
        cached = await self._get_cached(cache_key)
        if cached:
            return cached

        logger.info("Getting GLPI user profile", data={"user_id": user_id})

        try:
            # Get user details
            user_data = await self._request("GET", f"User/{user_id}")

            if not user_data:
                return None

            # Get user's profiles (roles)
            profiles = await self._request("GET", f"User/{user_id}/Profile_User")

            # Determine role based on profiles
            role = "technician"  # Default role
            is_admin = False

            if profiles and isinstance(profiles, list):
                for profile in profiles:
                    profile_id = profile.get("profiles_id", 0)
                    # Common GLPI profile IDs: 1=self-service, 2=observer, 3=admin, 4=super-admin, 6=technician
                    if profile_id in [3, 4]:  # Admin or Super-Admin
                        role = "admin"
                        is_admin = True
                        break
                    elif profile_id == 6:  # Technician
                        role = "technician"

            profile = {
                "id": user_data.get("id"),
                "name": user_data.get("realname", "") or user_data.get("name", ""),
                "firstname": user_data.get("firstname", ""),
                "email": user_data.get("email", ""),
                "role": role,
                "is_admin": is_admin,
                "permissions": {
                    "can_view_all_tickets": is_admin,
                    "can_update_any_ticket": is_admin,
                    "can_assign_tickets": is_admin,
                }
            }

            # Cache for 30 minutes
            await self._set_cached(cache_key, profile, 1800)
            logger.info("GLPI user profile retrieved", data={"user_id": user_id, "role": role})
            return profile

        except GLPINotFoundError:
            return None
        except Exception as e:
            logger.error(f"Error getting user profile: {e}")
            return None

    async def get_tickets_assigned_to_user(
        self,
        user_id: int,
        status: Optional[str] = None,
        priority: Optional[int] = None,
        search: Optional[str] = None,
        limit: int = 20,
        include_requester: bool = True
    ) -> List[GLPITicket]:
        """
        Get tickets assigned to or created by a specific user.

        Args:
            user_id: The GLPI user ID
            status: Filter by status ('new', 'assigned', 'pending', 'solved', 'closed', 'open', 'all')
            priority: Filter by priority (1-5)
            search: Optional search query
            limit: Maximum results
            include_requester: Also include tickets where user is the requester

        Returns:
            List of tickets related to the user
        """
        logger.info("Getting tickets for user", data={
            "user_id": user_id,
            "status": status,
            "include_requester": include_requester
        })

        # Build search parameters
        params = {
            "forcedisplay[0]": 1,   # ID
            "forcedisplay[1]": 2,   # Name
            "forcedisplay[2]": 21,  # Content
            "forcedisplay[3]": 12,  # Status
            "forcedisplay[4]": 10,  # Urgency
            "forcedisplay[5]": 11,  # Impact
            "forcedisplay[6]": 7,   # Category
            "forcedisplay[7]": 3,   # Priority
            "forcedisplay[8]": 5,   # Technician
            "forcedisplay[9]": 4,   # Requester
            "range": f"0-{limit - 1}",
            "sort": 19,  # Sort by modification date
            "order": "DESC",
        }

        criteria_idx = 0

        # Filter by assigned technician (field 5) OR requester (field 4)
        if include_requester:
            # Technician in charge
            params[f"criteria[{criteria_idx}][field]"] = 5
            params[f"criteria[{criteria_idx}][searchtype]"] = "equals"
            params[f"criteria[{criteria_idx}][value]"] = user_id
            criteria_idx += 1
            # OR Requester
            params[f"criteria[{criteria_idx}][link]"] = "OR"
            params[f"criteria[{criteria_idx}][field]"] = 4
            params[f"criteria[{criteria_idx}][searchtype]"] = "equals"
            params[f"criteria[{criteria_idx}][value]"] = user_id
            criteria_idx += 1
        else:
            # Only technician in charge
            params[f"criteria[{criteria_idx}][field]"] = 5
            params[f"criteria[{criteria_idx}][searchtype]"] = "equals"
            params[f"criteria[{criteria_idx}][value]"] = user_id
            criteria_idx += 1

        # Add status filter
        status_map = {
            "new": self.STATUS_NEW,
            "assigned": self.STATUS_ASSIGNED,
            "planned": self.STATUS_PLANNED,
            "pending": self.STATUS_PENDING,
            "solved": self.STATUS_SOLVED,
            "closed": self.STATUS_CLOSED,
        }

        if status and status != "all":
            if status == "open":
                # All open tickets (new, assigned, pending, planned)
                params[f"criteria[{criteria_idx}][link]"] = "AND"
                params[f"criteria[{criteria_idx}][field]"] = 12
                params[f"criteria[{criteria_idx}][searchtype]"] = "equals"
                params[f"criteria[{criteria_idx}][value]"] = self.STATUS_NEW
                criteria_idx += 1
                for s in [self.STATUS_ASSIGNED, self.STATUS_PENDING, self.STATUS_PLANNED]:
                    params[f"criteria[{criteria_idx}][link]"] = "OR"
                    params[f"criteria[{criteria_idx}][field]"] = 12
                    params[f"criteria[{criteria_idx}][searchtype]"] = "equals"
                    params[f"criteria[{criteria_idx}][value]"] = s
                    criteria_idx += 1
            elif status in status_map:
                params[f"criteria[{criteria_idx}][link]"] = "AND"
                params[f"criteria[{criteria_idx}][field]"] = 12
                params[f"criteria[{criteria_idx}][searchtype]"] = "equals"
                params[f"criteria[{criteria_idx}][value]"] = status_map[status]
                criteria_idx += 1

        # Add priority filter
        if priority:
            params[f"criteria[{criteria_idx}][link]"] = "AND"
            params[f"criteria[{criteria_idx}][field]"] = 3
            params[f"criteria[{criteria_idx}][searchtype]"] = "equals"
            params[f"criteria[{criteria_idx}][value]"] = priority
            criteria_idx += 1

        # Add search filter
        if search and search.strip():
            params[f"criteria[{criteria_idx}][link]"] = "AND"
            params[f"criteria[{criteria_idx}][field]"] = 1  # Name
            params[f"criteria[{criteria_idx}][searchtype]"] = "contains"
            params[f"criteria[{criteria_idx}][value]"] = search.strip()
            criteria_idx += 1

        try:
            result = await self._request("GET", "search/Ticket", params=params)
            tickets = self._parse_ticket_search_results(result)
            logger.info("Found tickets for user", data={
                "user_id": user_id,
                "count": len(tickets),
                "status_filter": status
            })
            return tickets
        except GLPINotFoundError:
            logger.info("No tickets found for user", data={"user_id": user_id})
            return []
        except Exception as e:
            logger.error(f"Error getting user tickets: {e}", data={"user_id": user_id})
            return []

    async def get_all_tickets(
        self,
        status: Optional[str] = None,
        priority: Optional[int] = None,
        search: Optional[str] = None,
        limit: int = 20
    ) -> List[GLPITicket]:
        """
        Get all tickets (for admin users).

        Args:
            status: Filter by status ('new', 'assigned', 'pending', 'solved', 'closed', 'open', 'all')
            priority: Filter by priority (1-5)
            search: Optional search query
            limit: Maximum results

        Returns:
            List of tickets
        """
        logger.info("Getting all tickets (admin)", data={"status": status, "limit": limit})

        # Build search parameters
        params = {
            "forcedisplay[0]": 1,   # ID
            "forcedisplay[1]": 2,   # Name
            "forcedisplay[2]": 21,  # Content
            "forcedisplay[3]": 12,  # Status
            "forcedisplay[4]": 10,  # Urgency
            "forcedisplay[5]": 11,  # Impact
            "forcedisplay[6]": 7,   # Category
            "forcedisplay[7]": 3,   # Priority
            "forcedisplay[8]": 5,   # Technician
            "forcedisplay[9]": 4,   # Requester
            "range": f"0-{limit - 1}",
            "sort": 19,  # Sort by modification date
            "order": "DESC",
        }

        criteria_idx = 0

        # Add status filter
        status_map = {
            "new": self.STATUS_NEW,
            "assigned": self.STATUS_ASSIGNED,
            "planned": self.STATUS_PLANNED,
            "pending": self.STATUS_PENDING,
            "solved": self.STATUS_SOLVED,
            "closed": self.STATUS_CLOSED,
        }

        if status and status != "all":
            if status == "open":
                # All open tickets (new, assigned, pending, planned)
                params[f"criteria[{criteria_idx}][field]"] = 12
                params[f"criteria[{criteria_idx}][searchtype]"] = "equals"
                params[f"criteria[{criteria_idx}][value]"] = self.STATUS_NEW
                criteria_idx += 1
                for s in [self.STATUS_ASSIGNED, self.STATUS_PENDING, self.STATUS_PLANNED]:
                    params[f"criteria[{criteria_idx}][link]"] = "OR"
                    params[f"criteria[{criteria_idx}][field]"] = 12
                    params[f"criteria[{criteria_idx}][searchtype]"] = "equals"
                    params[f"criteria[{criteria_idx}][value]"] = s
                    criteria_idx += 1
            elif status in status_map:
                params[f"criteria[{criteria_idx}][field]"] = 12
                params[f"criteria[{criteria_idx}][searchtype]"] = "equals"
                params[f"criteria[{criteria_idx}][value]"] = status_map[status]
                criteria_idx += 1

        # Add priority filter
        if priority:
            if criteria_idx > 0:
                params[f"criteria[{criteria_idx}][link]"] = "AND"
            params[f"criteria[{criteria_idx}][field]"] = 3
            params[f"criteria[{criteria_idx}][searchtype]"] = "equals"
            params[f"criteria[{criteria_idx}][value]"] = priority
            criteria_idx += 1

        # Add search filter
        if search and search.strip():
            if criteria_idx > 0:
                params[f"criteria[{criteria_idx}][link]"] = "AND"
            params[f"criteria[{criteria_idx}][field]"] = 1  # Name
            params[f"criteria[{criteria_idx}][searchtype]"] = "contains"
            params[f"criteria[{criteria_idx}][value]"] = search.strip()
            criteria_idx += 1

        try:
            result = await self._request("GET", "search/Ticket", params=params)
            tickets = self._parse_ticket_search_results(result)
            logger.info("Found all tickets", data={"count": len(tickets), "status_filter": status})
            return tickets
        except GLPINotFoundError:
            logger.info("No tickets found")
            return []
        except Exception as e:
            logger.error(f"Error getting all tickets: {e}")
            return []

    async def update_ticket(
        self,
        ticket_id: int,
        status: Optional[int] = None,
        priority: Optional[int] = None,
        urgency: Optional[int] = None,
        impact: Optional[int] = None,
        category_id: Optional[int] = None,
        assigned_to: Optional[int] = None,
        users_id: Optional[int] = None
    ) -> bool:
        """
        Update ticket fields.

        Args:
            ticket_id: The ticket ID
            status: New status (1-6)
            priority: New priority (1-5)
            urgency: New urgency (1-5)
            impact: New impact (1-5)
            category_id: New category ID
            assigned_to: New technician user ID
            users_id: User making the change (for attribution)

        Returns:
            True if update successful, False otherwise
        """
        logger.info("Updating ticket", data={"ticket_id": ticket_id, "users_id": users_id})

        # Build update payload
        update_fields = {}

        if status is not None:
            update_fields["status"] = status
        if priority is not None:
            update_fields["priority"] = priority
        if urgency is not None:
            update_fields["urgency"] = urgency
        if impact is not None:
            update_fields["impact"] = impact
        if category_id is not None:
            update_fields["itilcategories_id"] = category_id

        if not update_fields:
            logger.warning("No fields to update")
            return False

        payload = {"input": update_fields}

        try:
            await self._request("PUT", f"Ticket/{ticket_id}", json_data=payload)

            # Handle technician assignment separately
            if assigned_to is not None:
                await self._assign_ticket_to_user(ticket_id, assigned_to)

            logger.info("Ticket updated successfully", data={"ticket_id": ticket_id})
            return True

        except GLPIError as e:
            logger.error(f"Error updating ticket: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error updating ticket: {e}")
            raise GLPIError(f"Failed to update ticket: {e}")

    async def _assign_ticket_to_user(self, ticket_id: int, user_id: int) -> bool:
        """
        Assign a ticket to a technician.

        Args:
            ticket_id: The ticket ID
            user_id: The technician's user ID

        Returns:
            True if assignment successful
        """
        payload = {
            "input": {
                "tickets_id": ticket_id,
                "users_id": user_id,
                "type": 2,  # 2 = assigned to (technician)
            }
        }

        try:
            await self._request("POST", "Ticket_User", json_data=payload)
            logger.info("Ticket assigned", data={"ticket_id": ticket_id, "user_id": user_id})
            return True
        except Exception as e:
            logger.error(f"Error assigning ticket: {e}")
            return False

    async def check_ticket_access(self, ticket_id: int, user_id: int, is_admin: bool = False) -> bool:
        """
        Check if a user has access to a specific ticket.

        Args:
            ticket_id: The ticket ID
            user_id: The user ID to check
            is_admin: Whether the user is an admin

        Returns:
            True if user has access, False otherwise
        """
        if is_admin:
            return True

        try:
            # Get ticket's assigned users
            ticket_users = await self._request("GET", f"Ticket/{ticket_id}/Ticket_User")

            if ticket_users and isinstance(ticket_users, list):
                for tu in ticket_users:
                    if tu.get("users_id") == user_id and tu.get("type") == 2:  # type 2 = technician
                        return True

            return False

        except Exception as e:
            logger.error(f"Error checking ticket access: {e}")
            return False

    # Utility Methods

    async def test_connection(self) -> bool:
        """Test the GLPI connection."""
        try:
            await self._ensure_session()
            return True
        except Exception as e:
            logger.error(f"GLPI connection test failed: {e}")
            return False
