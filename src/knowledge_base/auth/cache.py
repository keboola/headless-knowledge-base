"""Permission caching using Redis."""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

# Default TTL for permission cache (5 minutes)
DEFAULT_PERMISSION_TTL = 300


class PermissionCache:
    """Cache for user permission checks.

    Caches whether a user can access specific pages to avoid
    repeated Confluence API calls.
    """

    def __init__(self, redis: "Redis", ttl_seconds: int = DEFAULT_PERMISSION_TTL):
        """Initialize permission cache.

        Args:
            redis: Redis client instance
            ttl_seconds: Time-to-live for cached permissions
        """
        self.redis = redis
        self.ttl = ttl_seconds

    def _key(self, user_id: str, page_id: str) -> str:
        """Generate cache key for user-page permission."""
        return f"perm:{user_id}:{page_id}"

    async def get(self, user_id: str, page_id: str) -> bool | None:
        """Get cached permission for user-page pair.

        Args:
            user_id: Slack user ID
            page_id: Confluence page ID

        Returns:
            True if allowed, False if denied, None if not cached
        """
        try:
            key = self._key(user_id, page_id)
            value = await self.redis.get(key)

            if value is None:
                return None

            return value == b"1"

        except Exception as e:
            logger.warning(f"Permission cache get failed: {e}")
            return None

    async def set(self, user_id: str, page_id: str, can_access: bool) -> None:
        """Cache permission for user-page pair.

        Args:
            user_id: Slack user ID
            page_id: Confluence page ID
            can_access: Whether user can access the page
        """
        try:
            key = self._key(user_id, page_id)
            value = "1" if can_access else "0"
            await self.redis.setex(key, self.ttl, value)

        except Exception as e:
            logger.warning(f"Permission cache set failed: {e}")

    async def invalidate_user(self, user_id: str) -> int:
        """Clear all cached permissions for a user.

        Used when user re-authenticates or token is refreshed.

        Args:
            user_id: Slack user ID

        Returns:
            Number of keys deleted
        """
        try:
            pattern = f"perm:{user_id}:*"
            keys = []

            async for key in self.redis.scan_iter(pattern):
                keys.append(key)

            if keys:
                deleted = await self.redis.delete(*keys)
                logger.info(f"Invalidated {deleted} permission cache entries for {user_id}")
                return deleted

            return 0

        except Exception as e:
            logger.warning(f"Permission cache invalidation failed: {e}")
            return 0

    async def invalidate_page(self, page_id: str) -> int:
        """Clear all cached permissions for a page.

        Used when page permissions change.

        Args:
            page_id: Confluence page ID

        Returns:
            Number of keys deleted
        """
        try:
            pattern = f"perm:*:{page_id}"
            keys = []

            async for key in self.redis.scan_iter(pattern):
                keys.append(key)

            if keys:
                deleted = await self.redis.delete(*keys)
                logger.info(f"Invalidated {deleted} permission cache entries for page {page_id}")
                return deleted

            return 0

        except Exception as e:
            logger.warning(f"Page permission cache invalidation failed: {e}")
            return 0

    async def get_batch(
        self, user_id: str, page_ids: list[str]
    ) -> dict[str, bool | None]:
        """Get cached permissions for multiple pages.

        Args:
            user_id: Slack user ID
            page_ids: List of Confluence page IDs

        Returns:
            Dict mapping page_id to permission (True/False/None)
        """
        if not page_ids:
            return {}

        try:
            keys = [self._key(user_id, page_id) for page_id in page_ids]
            values = await self.redis.mget(keys)

            result = {}
            for page_id, value in zip(page_ids, values):
                if value is None:
                    result[page_id] = None
                else:
                    result[page_id] = value == b"1"

            return result

        except Exception as e:
            logger.warning(f"Permission cache batch get failed: {e}")
            return {page_id: None for page_id in page_ids}

    async def set_batch(
        self, user_id: str, permissions: dict[str, bool]
    ) -> None:
        """Cache permissions for multiple pages.

        Args:
            user_id: Slack user ID
            permissions: Dict mapping page_id to permission
        """
        if not permissions:
            return

        try:
            pipe = self.redis.pipeline()

            for page_id, can_access in permissions.items():
                key = self._key(user_id, page_id)
                value = "1" if can_access else "0"
                pipe.setex(key, self.ttl, value)

            await pipe.execute()

        except Exception as e:
            logger.warning(f"Permission cache batch set failed: {e}")
