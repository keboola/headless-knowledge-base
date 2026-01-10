"""User-Confluence account linking functionality."""

import base64
import hashlib
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from cryptography.fernet import Fernet
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from knowledge_base.db.models import UserConfluenceLink

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _get_encryption_key() -> bytes:
    """Get or generate encryption key for tokens.

    Uses ENCRYPTION_KEY env var or derives from SECRET_KEY.
    """
    key = os.environ.get("ENCRYPTION_KEY")

    if key:
        # Use provided key (must be 32 bytes, base64 encoded)
        return base64.urlsafe_b64decode(key)

    # Derive from SECRET_KEY
    secret = os.environ.get("SECRET_KEY", "default-dev-secret-key")
    # Use SHA256 to get consistent 32-byte key
    derived = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(derived)


def encrypt_token(token: str) -> str:
    """Encrypt a token for storage.

    Args:
        token: Plain text token

    Returns:
        Encrypted token string
    """
    key = _get_encryption_key()
    f = Fernet(key)
    return f.encrypt(token.encode()).decode()


def decrypt_token(encrypted: str) -> str:
    """Decrypt a stored token.

    Args:
        encrypted: Encrypted token string

    Returns:
        Plain text token
    """
    key = _get_encryption_key()
    f = Fernet(key)
    return f.decrypt(encrypted.encode()).decode()


@dataclass
class LinkedAccount:
    """Represents a linked Confluence account."""

    slack_user_id: str
    confluence_account_id: str
    confluence_email: str | None
    is_active: bool
    linked_at: datetime
    last_used_at: datetime


class UserLinkManager:
    """Manage user-Confluence account links."""

    def __init__(self, session: Session):
        """Initialize link manager.

        Args:
            session: Database session
        """
        self.session = session

    def is_linked(self, slack_user_id: str) -> bool:
        """Check if a Slack user has linked their Confluence account.

        Args:
            slack_user_id: Slack user ID

        Returns:
            True if user is linked and active
        """
        link = self.session.execute(
            select(UserConfluenceLink).where(
                UserConfluenceLink.slack_user_id == slack_user_id,
                UserConfluenceLink.is_active == True,  # noqa: E712
            )
        ).scalar_one_or_none()

        return link is not None

    def get_link(self, slack_user_id: str) -> LinkedAccount | None:
        """Get user's linked account info (without tokens).

        Args:
            slack_user_id: Slack user ID

        Returns:
            LinkedAccount or None if not linked
        """
        link = self.session.execute(
            select(UserConfluenceLink).where(
                UserConfluenceLink.slack_user_id == slack_user_id
            )
        ).scalar_one_or_none()

        if not link:
            return None

        return LinkedAccount(
            slack_user_id=link.slack_user_id,
            confluence_account_id=link.confluence_account_id,
            confluence_email=link.confluence_email,
            is_active=link.is_active,
            linked_at=link.linked_at,
            last_used_at=link.last_used_at,
        )

    def get_access_token(self, slack_user_id: str) -> str | None:
        """Get decrypted access token for a user.

        Args:
            slack_user_id: Slack user ID

        Returns:
            Decrypted access token or None
        """
        link = self.session.execute(
            select(UserConfluenceLink).where(
                UserConfluenceLink.slack_user_id == slack_user_id,
                UserConfluenceLink.is_active == True,  # noqa: E712
            )
        ).scalar_one_or_none()

        if not link:
            return None

        try:
            # Update last used timestamp
            self.session.execute(
                update(UserConfluenceLink)
                .where(UserConfluenceLink.slack_user_id == slack_user_id)
                .values(last_used_at=datetime.utcnow())
            )
            self.session.commit()

            return decrypt_token(link.access_token)

        except Exception as e:
            logger.error(f"Failed to decrypt token for {slack_user_id}: {e}")
            return None

    def create_or_update_link(
        self,
        slack_user_id: str,
        slack_username: str,
        confluence_account_id: str,
        access_token: str,
        refresh_token: str | None = None,
        confluence_email: str | None = None,
        token_expires_at: datetime | None = None,
    ) -> UserConfluenceLink:
        """Create or update a user-Confluence link.

        Args:
            slack_user_id: Slack user ID
            slack_username: Slack username
            confluence_account_id: Confluence account ID
            access_token: OAuth access token (will be encrypted)
            refresh_token: OAuth refresh token (will be encrypted)
            confluence_email: User's Confluence email
            token_expires_at: Token expiration time

        Returns:
            Created or updated link
        """
        # Encrypt tokens
        encrypted_access = encrypt_token(access_token)
        encrypted_refresh = encrypt_token(refresh_token) if refresh_token else None

        # Check for existing link
        existing = self.session.execute(
            select(UserConfluenceLink).where(
                UserConfluenceLink.slack_user_id == slack_user_id
            )
        ).scalar_one_or_none()

        if existing:
            # Update existing link
            existing.slack_username = slack_username
            existing.confluence_account_id = confluence_account_id
            existing.confluence_email = confluence_email
            existing.access_token = encrypted_access
            existing.refresh_token = encrypted_refresh
            existing.token_expires_at = token_expires_at
            existing.is_active = True
            existing.last_refresh_at = datetime.utcnow()

            self.session.commit()
            logger.info(f"Updated Confluence link for Slack user {slack_user_id}")
            return existing

        # Create new link
        link = UserConfluenceLink(
            slack_user_id=slack_user_id,
            slack_username=slack_username,
            confluence_account_id=confluence_account_id,
            confluence_email=confluence_email,
            access_token=encrypted_access,
            refresh_token=encrypted_refresh,
            token_expires_at=token_expires_at,
        )

        self.session.add(link)
        self.session.commit()

        logger.info(f"Created Confluence link for Slack user {slack_user_id}")
        return link

    def deactivate_link(self, slack_user_id: str) -> bool:
        """Deactivate a user's Confluence link.

        Args:
            slack_user_id: Slack user ID

        Returns:
            True if link was deactivated
        """
        result = self.session.execute(
            update(UserConfluenceLink)
            .where(UserConfluenceLink.slack_user_id == slack_user_id)
            .values(is_active=False)
        )

        self.session.commit()

        if result.rowcount > 0:
            logger.info(f"Deactivated Confluence link for Slack user {slack_user_id}")
            return True

        return False

    def refresh_tokens(
        self,
        slack_user_id: str,
        access_token: str,
        refresh_token: str | None = None,
        token_expires_at: datetime | None = None,
    ) -> bool:
        """Update tokens after OAuth refresh.

        Args:
            slack_user_id: Slack user ID
            access_token: New access token
            refresh_token: New refresh token (optional)
            token_expires_at: New expiration time

        Returns:
            True if tokens were updated
        """
        encrypted_access = encrypt_token(access_token)
        encrypted_refresh = encrypt_token(refresh_token) if refresh_token else None

        values = {
            "access_token": encrypted_access,
            "last_refresh_at": datetime.utcnow(),
        }

        if encrypted_refresh:
            values["refresh_token"] = encrypted_refresh

        if token_expires_at:
            values["token_expires_at"] = token_expires_at

        result = self.session.execute(
            update(UserConfluenceLink)
            .where(UserConfluenceLink.slack_user_id == slack_user_id)
            .values(**values)
        )

        self.session.commit()

        if result.rowcount > 0:
            logger.info(f"Refreshed tokens for Slack user {slack_user_id}")
            return True

        return False
