"""Redis client for caching and message broker."""

import json
from typing import Any

import redis.asyncio as redis

from src.shared.config import get_settings
from src.shared.logger import get_logger

logger = get_logger(__name__)


class RedisClient:
    """Async Redis client wrapper."""
    
    def __init__(self) -> None:
        self._client: redis.Redis | None = None
        self._settings = get_settings()
    
    async def connect(self) -> None:
        """Connect to Redis."""
        try:
            self._client = redis.from_url(
                self._settings.redis_url,
                max_connections=self._settings.redis_max_connections,
                decode_responses=True,
            )
            await self._client.ping()
            logger.info("Redis connection established")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise
    
    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._client:
            await self._client.close()
            self._client = None
            logger.info("Redis connection closed")
    
    @property
    def client(self) -> redis.Redis:
        """Get Redis client instance."""
        if self._client is None:
            raise RuntimeError("Redis client not connected. Call connect() first.")
        return self._client
    
    async def get(self, key: str) -> str | None:
        """Get value by key."""
        return await self.client.get(key)
    
    async def get_json(self, key: str) -> Any | None:
        """Get and deserialize JSON value."""
        value = await self.get(key)
        if value:
            return json.loads(value)
        return None
    
    async def set(
        self,
        key: str,
        value: str,
        expire: int | None = None,
    ) -> bool:
        """Set value with optional expiration."""
        return await self.client.set(key, value, ex=expire)
    
    async def set_json(
        self,
        key: str,
        value: Any,
        expire: int | None = None,
    ) -> bool:
        """Serialize and set JSON value."""
        return await self.set(key, json.dumps(value), expire)
    
    async def delete(self, key: str) -> int:
        """Delete key."""
        return await self.client.delete(key)
    
    async def exists(self, key: str) -> bool:
        """Check if key exists."""
        return await self.client.exists(key) > 0
    
    async def increment(self, key: str, amount: int = 1) -> int:
        """Increment key value."""
        return await self.client.incrby(key, amount)
    
    async def expire(self, key: str, seconds: int) -> bool:
        """Set key expiration."""
        return await self.client.expire(key, seconds)
    
    async def rate_limit_check(
        self,
        key: str,
        max_requests: int,
        window_seconds: int,
    ) -> tuple[bool, int]:
        """Check rate limit.
        
        Returns:
            Tuple of (allowed, remaining_requests)
        """
        pipe = self.client.pipeline()
        now = await self.client.time()
        current_time = int(now[0])
        window_key = f"{key}:{current_time // window_seconds}"
        
        pipe.incr(window_key)
        pipe.expire(window_key, window_seconds + 1)
        results = await pipe.execute()
        
        current_count = results[0]
        allowed = current_count <= max_requests
        remaining = max(0, max_requests - current_count)
        
        return allowed, remaining


# Global Redis client instance
_redis_client: RedisClient | None = None


async def get_redis_client() -> RedisClient:
    """Get or create Redis client."""
    global _redis_client
    if _redis_client is None:
        _redis_client = RedisClient()
        await _redis_client.connect()
    return _redis_client


async def close_redis() -> None:
    """Close Redis connection."""
    global _redis_client
    if _redis_client:
        await _redis_client.disconnect()
        _redis_client = None
