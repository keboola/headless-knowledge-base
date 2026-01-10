"""Permission checking for Confluence pages."""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

from knowledge_base.auth.cache import PermissionCache
from knowledge_base.auth.confluence_link import UserLinkManager
from knowledge_base.config import settings

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass
class PermissionResult:
    """Result of permission check."""

    page_id: str
    can_access: bool
    cached: bool = False
    error: str | None = None


class PermissionChecker:
    """Check user permissions for Confluence pages."""

    def __init__(
        self,
        session: "Session",
        redis: "Redis",
        confluence_url: str | None = None,
    ):
        """Initialize permission checker.

        Args:
            session: Database session
            redis: Redis client for caching
            confluence_url: Confluence base URL (optional, uses settings)
        """
        self.link_manager = UserLinkManager(session)
        self.cache = PermissionCache(redis)
        self.confluence_url = confluence_url or settings.CONFLUENCE_URL

    async def can_access(self, slack_user_id: str, page_id: str) -> PermissionResult:
        """Check if user can access a Confluence page.

        Args:
            slack_user_id: Slack user ID
            page_id: Confluence page ID

        Returns:
            PermissionResult with access decision
        """
        # Check cache first
        cached = await self.cache.get(slack_user_id, page_id)
        if cached is not None:
            return PermissionResult(
                page_id=page_id,
                can_access=cached,
                cached=True,
            )

        # Get user's access token
        access_token = self.link_manager.get_access_token(slack_user_id)
        if not access_token:
            return PermissionResult(
                page_id=page_id,
                can_access=False,
                error="User not linked to Confluence",
            )

        # Check permission via Confluence API
        can_access = await self._check_confluence_permission(access_token, page_id)

        # Cache the result
        await self.cache.set(slack_user_id, page_id, can_access)

        return PermissionResult(
            page_id=page_id,
            can_access=can_access,
        )

    async def _check_confluence_permission(
        self, access_token: str, page_id: str
    ) -> bool:
        """Check permission via Confluence REST API.

        Args:
            access_token: User's OAuth access token
            page_id: Confluence page ID

        Returns:
            True if user can access the page
        """
        try:
            # Try to fetch the page with user's token
            # If successful, user has read access
            url = f"{self.confluence_url}/wiki/api/v2/pages/{page_id}"

            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/json",
                    },
                    timeout=10.0,
                )

                if response.status_code == 200:
                    return True
                elif response.status_code in (401, 403, 404):
                    # 401/403 = no permission, 404 = page doesn't exist or no permission
                    return False
                else:
                    logger.warning(
                        f"Unexpected status {response.status_code} checking permission for {page_id}"
                    )
                    return False

        except httpx.TimeoutException:
            logger.warning(f"Timeout checking permission for page {page_id}")
            # On timeout, deny access (fail closed)
            return False

        except Exception as e:
            logger.error(f"Error checking permission for page {page_id}: {e}")
            return False

    async def filter_results(
        self,
        slack_user_id: str,
        page_ids: list[str],
    ) -> list[str]:
        """Filter page IDs to only those user can access.

        Args:
            slack_user_id: Slack user ID
            page_ids: List of Confluence page IDs

        Returns:
            List of page IDs user can access
        """
        if not page_ids:
            return []

        # Check if user is linked
        if not self.link_manager.is_linked(slack_user_id):
            logger.debug(f"User {slack_user_id} not linked, denying all")
            return []

        # Get cached permissions
        cached_perms = await self.cache.get_batch(slack_user_id, page_ids)

        # Separate cached and uncached
        allowed = []
        to_check = []

        for page_id in page_ids:
            cached = cached_perms.get(page_id)
            if cached is True:
                allowed.append(page_id)
            elif cached is False:
                # Explicitly denied, skip
                pass
            else:
                # Not cached, need to check
                to_check.append(page_id)

        # Check uncached permissions
        if to_check:
            access_token = self.link_manager.get_access_token(slack_user_id)
            if access_token:
                new_perms = {}

                for page_id in to_check:
                    can_access = await self._check_confluence_permission(
                        access_token, page_id
                    )
                    new_perms[page_id] = can_access
                    if can_access:
                        allowed.append(page_id)

                # Cache new permissions
                await self.cache.set_batch(slack_user_id, new_perms)

        return allowed

    async def invalidate_user_cache(self, slack_user_id: str) -> int:
        """Invalidate all cached permissions for a user.

        Call this when user re-authenticates.

        Args:
            slack_user_id: Slack user ID

        Returns:
            Number of cache entries invalidated
        """
        return await self.cache.invalidate_user(slack_user_id)


class PermissionBypass:
    """Bypass permission checking (for development/testing)."""

    def __init__(self):
        """Initialize bypass checker."""
        pass

    async def can_access(self, slack_user_id: str, page_id: str) -> PermissionResult:
        """Always allow access."""
        return PermissionResult(page_id=page_id, can_access=True)

    async def filter_results(
        self, slack_user_id: str, page_ids: list[str]
    ) -> list[str]:
        """Return all page IDs."""
        return page_ids

    async def invalidate_user_cache(self, slack_user_id: str) -> int:
        """No-op for bypass."""
        return 0


def get_permission_checker(
    session: "Session",
    redis: "Redis | None" = None,
    bypass: bool = False,
) -> PermissionChecker | PermissionBypass:
    """Get appropriate permission checker.

    Args:
        session: Database session
        redis: Redis client (optional if bypass=True)
        bypass: If True, return a bypass checker that allows all

    Returns:
        Permission checker instance
    """
    if bypass:
        return PermissionBypass()

    if redis is None:
        raise ValueError("Redis client required for permission checking")

    return PermissionChecker(session, redis)
