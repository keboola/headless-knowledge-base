"""Confluence API client with rate limiting and retry logic."""

import asyncio
import base64
import logging
from collections.abc import AsyncIterator
from datetime import datetime

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from knowledge_base.config import settings
from knowledge_base.confluence.models import (
    Attachment,
    Page,
    PageContent,
    Permission,
)

logger = logging.getLogger(__name__)


class RateLimitError(Exception):
    """Raised when API rate limit is hit."""

    def __init__(self, retry_after: int = 60):
        self.retry_after = retry_after
        super().__init__(f"Rate limited. Retry after {retry_after}s")


class ConfluenceClient:
    """Async Confluence API client with rate limiting."""

    def __init__(
        self,
        url: str | None = None,
        username: str | None = None,
        api_token: str | None = None,
        requests_per_second: float = 5.0,
    ):
        self.url = (url or settings.CONFLUENCE_URL).rstrip("/")
        self.username = username or settings.CONFLUENCE_USERNAME
        self.api_token = api_token or settings.CONFLUENCE_API_TOKEN
        self.requests_per_second = requests_per_second
        self._last_request_time: float = 0.0
        self._user_cache: dict[str, str] = {}  # account_id -> display_name

        # Build auth header
        credentials = f"{self.username}:{self.api_token}"
        encoded = base64.b64encode(credentials.encode()).decode()
        self._auth_header = f"Basic {encoded}"

    async def _rate_limit(self) -> None:
        """Enforce rate limiting between requests."""
        min_interval = 1.0 / self.requests_per_second
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_request_time
        if elapsed < min_interval:
            await asyncio.sleep(min_interval - elapsed)
        self._last_request_time = asyncio.get_event_loop().time()

    @retry(
        retry=retry_if_exception_type((httpx.HTTPStatusError, RateLimitError)),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        stop=stop_after_attempt(5),
    )
    async def _request(
        self,
        method: str,
        endpoint: str,
        params: dict | None = None,
    ) -> dict:
        """Make an authenticated request to the Confluence API."""
        await self._rate_limit()

        url = f"{self.url}/wiki/api/v2{endpoint}"
        headers = {
            "Authorization": self._auth_header,
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(method, url, headers=headers, params=params)

            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 60))
                logger.warning(f"Rate limited. Waiting {retry_after}s...")
                raise RateLimitError(retry_after)

            response.raise_for_status()
            return response.json()

    async def _request_v1(
        self,
        method: str,
        endpoint: str,
        params: dict | None = None,
    ) -> dict:
        """Make a request to the V1 API (for some operations)."""
        await self._rate_limit()

        url = f"{self.url}/wiki/rest/api{endpoint}"
        headers = {
            "Authorization": self._auth_header,
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(method, url, headers=headers, params=params)

            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 60))
                logger.warning(f"Rate limited. Waiting {retry_after}s...")
                raise RateLimitError(retry_after)

            response.raise_for_status()
            return response.json()

    async def get_spaces(self) -> list[dict]:
        """Get all available spaces."""
        spaces = []
        cursor = None

        while True:
            params = {"limit": 100}
            if cursor:
                params["cursor"] = cursor

            data = await self._request("GET", "/spaces", params)
            spaces.extend(data.get("results", []))

            links = data.get("_links", {})
            if "next" not in links:
                break
            # Extract cursor from next link
            next_link = links["next"]
            if "cursor=" in next_link:
                cursor = next_link.split("cursor=")[1].split("&")[0]
            else:
                break

        return spaces

    async def get_all_pages(self, space_key: str) -> AsyncIterator[Page]:
        """Fetch all pages from a space with pagination."""
        cursor = None
        page_count = 0

        while True:
            params = {
                "space-id": await self._get_space_id(space_key),
                "limit": 100,
                "status": "current",
            }
            if cursor:
                params["cursor"] = cursor

            data = await self._request("GET", "/pages", params)

            for item in data.get("results", []):
                page_count += 1
                yield self._parse_page(item, space_key)

            links = data.get("_links", {})
            if "next" not in links:
                break
            next_link = links["next"]
            if "cursor=" in next_link:
                cursor = next_link.split("cursor=")[1].split("&")[0]
            else:
                break

        logger.info(f"Found {page_count} pages in space {space_key}")

    async def _get_space_id(self, space_key: str) -> str:
        """Get space ID from space key."""
        spaces = await self.get_spaces()
        for space in spaces:
            if space.get("key") == space_key:
                return space.get("id")
        raise ValueError(f"Space not found: {space_key}")

    async def _get_user_display_name(self, account_id: str) -> str:
        """Get user display name from account ID with caching."""
        if not account_id or account_id == "unknown":
            return ""

        if account_id in self._user_cache:
            return self._user_cache[account_id]

        try:
            # Use Atlassian User API
            await self._rate_limit()
            url = f"{self.url}/wiki/rest/api/user"
            headers = {
                "Authorization": self._auth_header,
                "Accept": "application/json",
            }
            params = {"accountId": account_id}

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, headers=headers, params=params)
                if response.status_code == 200:
                    data = response.json()
                    display_name = data.get("displayName", "")
                    self._user_cache[account_id] = display_name
                    return display_name
        except Exception as e:
            logger.debug(f"Failed to get display name for {account_id}: {e}")

        self._user_cache[account_id] = ""
        return ""

    async def _get_page_created_at(self, page_id: str) -> datetime | None:
        """Get page creation date from version history."""
        try:
            data = await self._request_v1(
                "GET",
                f"/content/{page_id}/history",
            )
            created_date = data.get("createdDate")
            if created_date:
                return self._parse_datetime(created_date)
        except Exception as e:
            logger.debug(f"Failed to get history for page {page_id}: {e}")
        return None

    def _parse_page(self, data: dict, space_key: str) -> Page:
        """Parse API response into Page model."""
        version = data.get("version", {})
        # Note: version.createdAt is when THIS version was created (i.e., last update time)
        # For actual page creation date, we need the history API (fetched in get_page_content)
        version_created = self._parse_datetime(version.get("createdAt"))
        return Page(
            id=str(data["id"]),
            title=data.get("title", "Untitled"),
            space_key=space_key,
            url=f"{self.url}/wiki{data.get('_links', {}).get('webui', '')}",
            status=data.get("status", "current"),
            created_at=version_created,  # Placeholder; actual created_at from history API
            updated_at=version_created,  # This is correct - when current version was created
            author=version.get("authorId", "unknown"),
            author_name="",  # Fetched during get_page_content
            version_number=version.get("number", 1),
            parent_id=data.get("parentId"),
        )

    async def get_page_content(self, page_id: str, space_key: str) -> PageContent:
        """Fetch full page content including body."""
        # Get page with body content
        params = {"body-format": "storage"}
        data = await self._request("GET", f"/pages/{page_id}", params)

        # Get labels
        labels = await self._get_page_labels(page_id)

        # Get permissions (using v1 API)
        permissions = await self._get_page_permissions(page_id)

        # Get attachments
        attachments = await self._get_page_attachments(page_id)

        version = data.get("version", {})
        body = data.get("body", {}).get("storage", {}).get("value", "")

        # Get author info
        author_id = version.get("authorId", "unknown")
        author_name = await self._get_user_display_name(author_id)

        # version.createdAt is when THIS version was created (i.e., last update time)
        updated_at = self._parse_datetime(version.get("createdAt"))

        # Get actual page creation date from history API
        created_at = await self._get_page_created_at(page_id)
        if created_at is None:
            created_at = updated_at  # Fallback to version date

        return PageContent(
            id=str(data["id"]),
            title=data.get("title", "Untitled"),
            space_key=space_key,
            url=f"{self.url}/wiki{data.get('_links', {}).get('webui', '')}",
            html_content=body,
            author=author_id,
            author_name=author_name,
            parent_id=data.get("parentId"),
            created_at=created_at,
            updated_at=updated_at,
            version_number=version.get("number", 1),
            status=data.get("status", "current"),
            labels=labels,
            permissions=permissions,
            attachments=attachments,
        )

    async def _get_page_labels(self, page_id: str) -> list[str]:
        """Get labels for a page."""
        try:
            data = await self._request("GET", f"/pages/{page_id}/labels")
            return [label.get("name", "") for label in data.get("results", [])]
        except Exception as e:
            logger.warning(f"Failed to get labels for page {page_id}: {e}")
            return []

    async def _get_page_permissions(self, page_id: str) -> list[Permission]:
        """Get permissions for a page using V1 API."""
        try:
            data = await self._request_v1(
                "GET",
                f"/content/{page_id}/restriction",
                params={"expand": "restrictions.user,restrictions.group"},
            )

            permissions = []
            for restriction in data.get("results", []):
                operation = restriction.get("operation", "read")
                for user in restriction.get("restrictions", {}).get("user", {}).get("results", []):
                    permissions.append(
                        Permission(
                            type="user",
                            name=user.get("username", user.get("accountId", "")),
                            operation=operation,
                        )
                    )
                for group in (
                    restriction.get("restrictions", {}).get("group", {}).get("results", [])
                ):
                    permissions.append(
                        Permission(
                            type="group",
                            name=group.get("name", ""),
                            operation=operation,
                        )
                    )
            return permissions
        except Exception as e:
            logger.warning(f"Failed to get permissions for page {page_id}: {e}")
            return []

    async def _get_page_attachments(self, page_id: str) -> list[Attachment]:
        """Get attachments for a page."""
        try:
            data = await self._request("GET", f"/pages/{page_id}/attachments")
            attachments = []
            for att in data.get("results", []):
                attachments.append(
                    Attachment(
                        id=str(att["id"]),
                        title=att.get("title", ""),
                        media_type=att.get("mediaType", "application/octet-stream"),
                        file_size=att.get("fileSize", 0),
                        download_url=f"{self.url}/wiki{att.get('_links', {}).get('download', '')}",
                    )
                )
            return attachments
        except Exception as e:
            logger.warning(f"Failed to get attachments for page {page_id}: {e}")
            return []

    @staticmethod
    def _parse_datetime(dt_str: str | None) -> datetime:
        """Parse ISO datetime string."""
        if not dt_str:
            return datetime.utcnow()
        try:
            # Handle ISO format with Z suffix
            if dt_str.endswith("Z"):
                dt_str = dt_str[:-1] + "+00:00"
            return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        except ValueError:
            return datetime.utcnow()
