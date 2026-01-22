"""
Redis cache service for Helpdesk AI.
"""
import json
from typing import Any, Optional
import redis.asyncio as redis
from redis.asyncio.connection import ConnectionPool

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class CacheService:
    """
    Async Redis cache service.

    Provides caching for GLPI search results and session data.
    """

    def __init__(self):
        self._pool: Optional[ConnectionPool] = None
        self._client: Optional[redis.Redis] = None
        self._connected: bool = False

    async def connect(self) -> bool:
        """Initialize Redis connection."""
        settings = get_settings()

        try:
            self._pool = ConnectionPool.from_url(
                settings.redis.url,
                decode_responses=True,
                max_connections=10,
            )
            self._client = redis.Redis(connection_pool=self._pool)

            # Test connection
            await self._client.ping()
            self._connected = True
            logger.info("Redis cache connected")
            return True

        except Exception as e:
            logger.warning(f"Redis connection failed: {e}. Running without cache.")
            self._connected = False
            return False

    async def disconnect(self):
        """Close Redis connection."""
        if self._client:
            await self._client.close()
        if self._pool:
            await self._pool.disconnect()
        self._connected = False
        logger.info("Redis cache disconnected")

    @property
    def is_connected(self) -> bool:
        """Check if cache is connected."""
        return self._connected

    async def get(self, key: str) -> Optional[Any]:
        """
        Get a value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found/error
        """
        if not self._connected:
            return None

        try:
            value = await self._client.get(key)
            if value:
                return json.loads(value)
            return None

        except json.JSONDecodeError:
            return value
        except Exception as e:
            logger.warning(f"Cache get error for key {key}: {e}")
            return None

    async def set(self, key: str, value: Any, ttl: int = 3600) -> bool:
        """
        Set a value in cache.

        Args:
            key: Cache key
            value: Value to cache (will be JSON serialized)
            ttl: Time to live in seconds

        Returns:
            True if successful, False otherwise
        """
        if not self._connected:
            return False

        try:
            serialized = json.dumps(value, default=str)
            await self._client.setex(key, ttl, serialized)
            return True

        except Exception as e:
            logger.warning(f"Cache set error for key {key}: {e}")
            return False

    async def delete(self, key: str) -> bool:
        """
        Delete a key from cache.

        Args:
            key: Cache key

        Returns:
            True if deleted, False otherwise
        """
        if not self._connected:
            return False

        try:
            await self._client.delete(key)
            return True

        except Exception as e:
            logger.warning(f"Cache delete error for key {key}: {e}")
            return False

    async def exists(self, key: str) -> bool:
        """
        Check if a key exists in cache.

        Args:
            key: Cache key

        Returns:
            True if exists, False otherwise
        """
        if not self._connected:
            return False

        try:
            return bool(await self._client.exists(key))

        except Exception as e:
            logger.warning(f"Cache exists error for key {key}: {e}")
            return False

    async def increment(self, key: str, ttl: Optional[int] = None) -> int:
        """
        Increment a counter in cache.

        Args:
            key: Cache key
            ttl: Optional TTL for new keys

        Returns:
            New counter value
        """
        if not self._connected:
            return 0

        try:
            value = await self._client.incr(key)
            if ttl and value == 1:
                await self._client.expire(key, ttl)
            return value

        except Exception as e:
            logger.warning(f"Cache increment error for key {key}: {e}")
            return 0

    async def get_ttl(self, key: str) -> int:
        """
        Get remaining TTL for a key.

        Args:
            key: Cache key

        Returns:
            TTL in seconds, -1 if no TTL, -2 if key doesn't exist
        """
        if not self._connected:
            return -2

        try:
            return await self._client.ttl(key)

        except Exception as e:
            logger.warning(f"Cache TTL error for key {key}: {e}")
            return -2

    # Session management methods

    async def get_session(self, session_id: str) -> Optional[dict]:
        """Get session data."""
        return await self.get(f"session:{session_id}")

    async def set_session(self, session_id: str, data: dict, ttl: Optional[int] = None) -> bool:
        """Set session data."""
        settings = get_settings()
        session_ttl = ttl or (settings.app.session_ttl_minutes * 60)
        return await self.set(f"session:{session_id}", data, session_ttl)

    async def delete_session(self, session_id: str) -> bool:
        """Delete session data."""
        return await self.delete(f"session:{session_id}")

    async def extend_session(self, session_id: str) -> bool:
        """Extend session TTL."""
        if not self._connected:
            return False

        settings = get_settings()
        ttl = settings.app.session_ttl_minutes * 60

        try:
            return bool(await self._client.expire(f"session:{session_id}", ttl))

        except Exception as e:
            logger.warning(f"Session extend error: {e}")
            return False


# Singleton instance
_cache_instance: Optional[CacheService] = None


async def get_cache() -> CacheService:
    """Get the cache service singleton."""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = CacheService()
        await _cache_instance.connect()
    return _cache_instance


async def close_cache():
    """Close the cache service."""
    global _cache_instance
    if _cache_instance:
        await _cache_instance.disconnect()
        _cache_instance = None
