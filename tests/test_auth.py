"""Tests for the authentication and permission module."""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from knowledge_base.auth.confluence_link import (
    encrypt_token,
    decrypt_token,
    UserLinkManager,
    LinkedAccount,
)
from knowledge_base.auth.cache import PermissionCache
from knowledge_base.auth.permissions import (
    PermissionChecker,
    PermissionBypass,
    PermissionResult,
    get_permission_checker,
)


class TestTokenEncryption:
    """Tests for token encryption/decryption."""

    def test_encrypt_decrypt_roundtrip(self):
        """Test that encryption and decryption are reversible."""
        os.environ["SECRET_KEY"] = "test-secret-key-for-testing"
        original = "my-super-secret-token-12345"

        encrypted = encrypt_token(original)
        decrypted = decrypt_token(encrypted)

        assert decrypted == original
        assert encrypted != original

    def test_different_tokens_produce_different_ciphertext(self):
        """Test that different tokens produce different encrypted values."""
        os.environ["SECRET_KEY"] = "test-secret-key-for-testing"
        token1 = "token-one"
        token2 = "token-two"

        encrypted1 = encrypt_token(token1)
        encrypted2 = encrypt_token(token2)

        assert encrypted1 != encrypted2


class TestPermissionCache:
    """Tests for PermissionCache."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        redis = MagicMock()
        redis.get = AsyncMock(return_value=None)
        redis.setex = AsyncMock()
        redis.mget = AsyncMock(return_value=[])
        redis.pipeline = MagicMock()
        redis.delete = AsyncMock(return_value=0)
        redis.scan_iter = MagicMock(return_value=iter([]))
        return redis

    @pytest.mark.asyncio
    async def test_get_returns_none_when_not_cached(self, mock_redis):
        """Test get returns None for uncached permission."""
        cache = PermissionCache(mock_redis)
        result = await cache.get("user123", "page456")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_returns_true_for_allowed(self, mock_redis):
        """Test get returns True when cached as allowed."""
        mock_redis.get = AsyncMock(return_value=b"1")
        cache = PermissionCache(mock_redis)
        result = await cache.get("user123", "page456")
        assert result is True

    @pytest.mark.asyncio
    async def test_get_returns_false_for_denied(self, mock_redis):
        """Test get returns False when cached as denied."""
        mock_redis.get = AsyncMock(return_value=b"0")
        cache = PermissionCache(mock_redis)
        result = await cache.get("user123", "page456")
        assert result is False

    @pytest.mark.asyncio
    async def test_set_caches_permission(self, mock_redis):
        """Test set caches permission with TTL."""
        cache = PermissionCache(mock_redis, ttl_seconds=300)
        await cache.set("user123", "page456", True)

        mock_redis.setex.assert_called_once()
        args = mock_redis.setex.call_args[0]
        assert "user123" in args[0]
        assert "page456" in args[0]
        assert args[1] == 300
        assert args[2] == "1"

    @pytest.mark.asyncio
    async def test_get_batch_returns_dict(self, mock_redis):
        """Test get_batch returns dictionary of permissions."""
        mock_redis.mget = AsyncMock(return_value=[b"1", None, b"0"])
        cache = PermissionCache(mock_redis)

        result = await cache.get_batch("user123", ["page1", "page2", "page3"])

        assert result["page1"] is True
        assert result["page2"] is None
        assert result["page3"] is False


class TestPermissionResult:
    """Tests for PermissionResult dataclass."""

    def test_allowed_result(self):
        """Test creating an allowed result."""
        result = PermissionResult(page_id="123", can_access=True)
        assert result.page_id == "123"
        assert result.can_access is True
        assert result.cached is False
        assert result.error is None

    def test_denied_result_with_error(self):
        """Test creating a denied result with error."""
        result = PermissionResult(
            page_id="123",
            can_access=False,
            error="User not linked"
        )
        assert result.can_access is False
        assert result.error == "User not linked"

    def test_cached_result(self):
        """Test creating a cached result."""
        result = PermissionResult(page_id="123", can_access=True, cached=True)
        assert result.cached is True


class TestPermissionBypass:
    """Tests for PermissionBypass."""

    @pytest.mark.asyncio
    async def test_can_access_always_true(self):
        """Test bypass always allows access."""
        bypass = PermissionBypass()
        result = await bypass.can_access("user123", "page456")
        assert result.can_access is True

    @pytest.mark.asyncio
    async def test_filter_results_returns_all(self):
        """Test bypass returns all page IDs."""
        bypass = PermissionBypass()
        page_ids = ["page1", "page2", "page3"]
        result = await bypass.filter_results("user123", page_ids)
        assert result == page_ids


class TestUserLinkManager:
    """Tests for UserLinkManager."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.execute = MagicMock()
        session.add = MagicMock()
        session.commit = MagicMock()
        return session

    def test_is_linked_returns_false_when_no_link(self, mock_session):
        """Test is_linked returns False when user not linked."""
        mock_session.execute.return_value.scalar_one_or_none.return_value = None
        manager = UserLinkManager(mock_session)

        result = manager.is_linked("user123")
        assert result is False

    def test_is_linked_returns_true_when_linked(self, mock_session):
        """Test is_linked returns True when user is linked."""
        mock_link = MagicMock()
        mock_link.is_active = True
        mock_session.execute.return_value.scalar_one_or_none.return_value = mock_link
        manager = UserLinkManager(mock_session)

        result = manager.is_linked("user123")
        assert result is True

    def test_get_link_returns_linked_account(self, mock_session):
        """Test get_link returns LinkedAccount object."""
        mock_link = MagicMock()
        mock_link.slack_user_id = "user123"
        mock_link.confluence_account_id = "conf456"
        mock_link.confluence_email = "test@example.com"
        mock_link.is_active = True
        mock_link.linked_at = datetime.utcnow()
        mock_link.last_used_at = datetime.utcnow()
        mock_session.execute.return_value.scalar_one_or_none.return_value = mock_link

        manager = UserLinkManager(mock_session)
        result = manager.get_link("user123")

        assert isinstance(result, LinkedAccount)
        assert result.slack_user_id == "user123"
        assert result.confluence_account_id == "conf456"

    def test_get_link_returns_none_when_not_linked(self, mock_session):
        """Test get_link returns None when user not linked."""
        mock_session.execute.return_value.scalar_one_or_none.return_value = None
        manager = UserLinkManager(mock_session)

        result = manager.get_link("user123")
        assert result is None


class TestPermissionChecker:
    """Tests for PermissionChecker."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        return session

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        redis = MagicMock()
        redis.get = AsyncMock(return_value=None)
        redis.setex = AsyncMock()
        redis.mget = AsyncMock(return_value=[])
        return redis

    @pytest.mark.asyncio
    async def test_can_access_returns_cached_result(self, mock_session, mock_redis):
        """Test can_access returns cached permission."""
        mock_redis.get = AsyncMock(return_value=b"1")

        checker = PermissionChecker(mock_session, mock_redis)
        result = await checker.can_access("user123", "page456")

        assert result.can_access is True
        assert result.cached is True

    @pytest.mark.asyncio
    async def test_can_access_denies_unlinked_user(self, mock_session, mock_redis):
        """Test can_access denies access for unlinked user."""
        mock_redis.get = AsyncMock(return_value=None)  # Not cached
        mock_session.execute.return_value.scalar_one_or_none.return_value = None  # Not linked

        checker = PermissionChecker(mock_session, mock_redis)
        result = await checker.can_access("user123", "page456")

        assert result.can_access is False
        assert "not linked" in result.error.lower()

    @pytest.mark.asyncio
    async def test_filter_results_returns_empty_for_unlinked(self, mock_session, mock_redis):
        """Test filter_results returns empty for unlinked user."""
        mock_session.execute.return_value.scalar_one_or_none.return_value = None

        checker = PermissionChecker(mock_session, mock_redis)
        result = await checker.filter_results("user123", ["page1", "page2"])

        assert result == []


class TestGetPermissionChecker:
    """Tests for get_permission_checker factory function."""

    def test_returns_bypass_when_bypass_true(self):
        """Test factory returns bypass checker when bypass=True."""
        checker = get_permission_checker(MagicMock(), bypass=True)
        assert isinstance(checker, PermissionBypass)

    def test_raises_without_redis_when_not_bypass(self):
        """Test factory raises when Redis not provided and not bypass."""
        with pytest.raises(ValueError) as exc_info:
            get_permission_checker(MagicMock(), redis=None, bypass=False)
        assert "Redis" in str(exc_info.value)

    def test_returns_checker_with_redis(self):
        """Test factory returns PermissionChecker when Redis provided."""
        checker = get_permission_checker(MagicMock(), redis=MagicMock())
        assert isinstance(checker, PermissionChecker)
