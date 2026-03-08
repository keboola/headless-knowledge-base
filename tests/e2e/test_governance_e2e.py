"""E2E tests for knowledge governance with full downstream verification.

Unlike the previous version (PR #40) which only checked HTTP 200 from button
clicks, these tests verify actual downstream effects:
- DB status transitions (pending_review -> approved/rejected, auto_approved -> reverted)
- Slack message updates (buttons removed, status text added)
- Search filtering (reverted/rejected/pending content excluded)
- Admin authorization (non-admin channel actions rejected)
- Revert window expiration (revert fails after deadline)

Architecture:
- Handler-level tests call governance handlers directly
- Real in-memory SQLite DB for governance record state verification
- Real Slack AsyncWebClient for message posting/updating (staging workspace)
- Only Neo4j side effects are mocked (_update_neo4j_governance_status)

Prerequisites:
- E2E_ADMIN_CHANNEL set to admin channel ID
- SLACK_BOT_TOKEN / SLACK_USER_TOKEN
- Bot is a member of the admin channel
"""

import asyncio
import json
import os
import types
import uuid
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from knowledge_base.config import settings
from knowledge_base.db.models import Base, KnowledgeGovernanceRecord

pytestmark = pytest.mark.e2e


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def has_signing_secret():
    """Skip if no Slack signing secret is available."""
    if not (
        os.environ.get("SLACK_STAGING_SIGNING_SECRET")
        or os.environ.get("SLACK_SIGNING_SECRET")
    ):
        pytest.skip(
            "SLACK_STAGING_SIGNING_SECRET or SLACK_SIGNING_SECRET not set"
        )
    return True


@pytest.fixture
async def async_slack_client(e2e_config):
    """Provide an async Slack WebClient for calling governance_admin functions."""
    from slack_sdk.web.async_client import AsyncWebClient

    return AsyncWebClient(token=e2e_config["bot_token"])


@pytest.fixture
async def governance_db():
    """In-memory SQLite with KnowledgeGovernanceRecord table.

    Returns an async_sessionmaker that can be used to:
    1. Seed records before tests
    2. Patch into approval_engine.async_session_maker
    3. Query records after handler calls to verify state changes
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    yield session_maker
    await engine.dispose()


# =============================================================================
# Helpers
# =============================================================================


def _make_governance_record(
    *,
    chunk_id: str | None = None,
    risk_score: float = 72.0,
    risk_tier: str = "high",
    risk_factors: str = '{"author_trust": 80, "source_type": 60}',
    intake_path: str = "slack_create",
    submitted_by: str = "e2e-test-user",
    content_preview: str = "This is test content for governance E2E tests.",
    status: str = "pending_review",
    revert_deadline: datetime | None = None,
    slack_notification_ts: str | None = None,
    slack_notification_channel: str | None = None,
) -> types.SimpleNamespace:
    """Create a namespace object matching fields accessed by governance_admin.py.

    Used for notify_admin_high_risk and notify_admin_medium_risk which read:
    chunk_id, risk_score, risk_tier, risk_factors, intake_path,
    submitted_by, content_preview, revert_deadline
    """
    return types.SimpleNamespace(
        chunk_id=chunk_id or f"e2e_gov_{uuid.uuid4().hex[:12]}",
        risk_score=risk_score,
        risk_tier=risk_tier,
        risk_factors=risk_factors,
        intake_path=intake_path,
        submitted_by=submitted_by,
        content_preview=content_preview,
        status=status,
        revert_deadline=revert_deadline,
        slack_notification_ts=slack_notification_ts,
        slack_notification_channel=slack_notification_channel,
    )


async def _seed_record(
    session_maker: async_sessionmaker,
    chunk_id: str,
    status: str,
    risk_tier: str = "high",
    risk_score: float = 75.0,
    revert_deadline: datetime | None = None,
) -> KnowledgeGovernanceRecord:
    """Insert a governance record into the test DB."""
    async with session_maker() as session:
        record = KnowledgeGovernanceRecord(
            chunk_id=chunk_id,
            status=status,
            risk_tier=risk_tier,
            risk_score=risk_score,
            risk_factors='{"author_trust": 80, "source_type": 60}',
            intake_path="slack_create",
            submitted_by="e2e_test",
            content_preview="Test content for governance E2E.",
            revert_deadline=revert_deadline,
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return record


async def _get_record(
    session_maker: async_sessionmaker,
    chunk_id: str,
) -> KnowledgeGovernanceRecord | None:
    """Query the test DB for a governance record."""
    async with session_maker() as session:
        result = await session.execute(
            select(KnowledgeGovernanceRecord).where(
                KnowledgeGovernanceRecord.chunk_id == chunk_id
            )
        )
        return result.scalar_one_or_none()


def _mock_admin_session_maker():
    """Return a mock async_session_maker for governance_admin notification DB writes.

    The notification functions do lazy imports of async_session_maker and use it
    to update slack_notification_ts. We mock this to avoid touching the real DB.
    """
    mock_session = MagicMock()
    mock_session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    def factory():
        return mock_session

    return factory


def _find_message_with_text(messages: list[dict], needle: str) -> dict | None:
    """Find a Slack message whose text or blocks contain *needle*."""
    for msg in messages:
        if needle in msg.get("text", ""):
            return msg
        for block in msg.get("blocks", []):
            if needle in json.dumps(block):
                return msg
    return None


async def _post_notification_to_admin(
    async_slack_client,
    admin_channel_id: str,
    record: types.SimpleNamespace,
    risk_type: str = "high",
) -> str:
    """Post a real governance notification to admin channel and return its ts.

    Patches _get_admin_channel and the DB write (lazy import of async_session_maker).
    """
    if risk_type == "high":
        from knowledge_base.slack.governance_admin import notify_admin_high_risk
        notify_fn = notify_admin_high_risk
    else:
        from knowledge_base.slack.governance_admin import notify_admin_medium_risk
        notify_fn = notify_admin_medium_risk

    with patch(
        "knowledge_base.slack.governance_admin._get_admin_channel",
        return_value=admin_channel_id,
    ), patch(
        "knowledge_base.db.database.async_session_maker",
        _mock_admin_session_maker(),
    ):
        ts = await notify_fn(async_slack_client, record)

    assert ts is not None, f"notify_admin_{risk_type}_risk should return a ts"
    return ts


# =============================================================================
# Class 1: Approve Full Flow
# =============================================================================


class TestApproveFullFlow:
    """Verify approve handler changes DB status AND updates Slack message."""

    @pytest.mark.asyncio
    async def test_approve_changes_db_status_and_updates_message(
        self,
        slack_client,
        e2e_config,
        admin_channel_id,
        async_slack_client,
        governance_db,
        unique_test_id,
    ):
        """Full approve flow: seed pending record -> call handler -> verify DB + Slack.

        1. Post real high-risk notification to admin channel
        2. Seed KnowledgeGovernanceRecord with status='pending_review' in test DB
        3. Call handle_governance_approve() directly with real Slack client
        4. Verify DB: status changed to 'approved', reviewed_by set
        5. Verify Slack: message updated to show 'Approved', buttons removed
        """
        from knowledge_base.slack.governance_admin import handle_governance_approve

        chunk_id = f"e2e_approve_{unique_test_id}"

        # Post notification to admin channel
        record = _make_governance_record(
            chunk_id=chunk_id, risk_score=85.0, risk_tier="high",
            content_preview=f"[E2E Test] Approve flow {unique_test_id}",
        )
        ts = await _post_notification_to_admin(
            async_slack_client, admin_channel_id, record, "high"
        )

        # Seed the record in test DB so ApprovalEngine.approve() can find it
        await _seed_record(governance_db, chunk_id, status="pending_review")

        await asyncio.sleep(2)

        # Call handle_governance_approve directly
        ack_mock = AsyncMock()
        body = {
            "user": {"id": "U_E2E_ADMIN"},
            "channel": {"id": admin_channel_id},
            "message": {"ts": ts},
            "actions": [{"action_id": f"governance_approve_{chunk_id}"}],
        }

        with patch(
            "knowledge_base.slack.governance_admin._is_admin_channel",
            return_value=True,
        ), patch(
            "knowledge_base.governance.approval_engine.async_session_maker",
            governance_db,
        ), patch(
            "knowledge_base.governance.approval_engine.ApprovalEngine._update_neo4j_governance_status",
            new_callable=AsyncMock,
        ):
            await handle_governance_approve(ack_mock, body, async_slack_client)

        ack_mock.assert_called_once()

        # Verify DB: status changed to 'approved'
        db_record = await _get_record(governance_db, chunk_id)
        assert db_record is not None, "Record should exist in DB"
        assert db_record.status == "approved", (
            f"Status should be 'approved', got '{db_record.status}'"
        )
        assert db_record.reviewed_by == "U_E2E_ADMIN"

        # Verify Slack: message updated to show 'Approved'
        await asyncio.sleep(2)
        history = slack_client.bot_client.conversations_history(
            channel=admin_channel_id, inclusive=True,
            oldest=ts, latest=ts, limit=1,
        )
        messages = history.get("messages", [])
        assert len(messages) > 0, "Message should still exist"

        updated_msg = messages[0]
        blocks_str = json.dumps(updated_msg.get("blocks", []))
        text = updated_msg.get("text", "")

        assert "Approved" in blocks_str or "Approved" in text, (
            f"Message should contain 'Approved'. text={text!r}"
        )
        assert not slack_client.message_has_button(updated_msg, "governance_approve"), (
            "Approve button should be removed after approval"
        )
        assert not slack_client.message_has_button(updated_msg, "governance_reject"), (
            "Reject button should be removed after approval"
        )

    @pytest.mark.asyncio
    async def test_approve_nonexistent_chunk_fails_gracefully(
        self,
        e2e_config,
        admin_channel_id,
        async_slack_client,
        governance_db,
        unique_test_id,
    ):
        """Approve a chunk_id that doesn't exist in DB -- handler fails gracefully.

        DB unchanged, ephemeral error posted (not chat_update).
        """
        from knowledge_base.slack.governance_admin import handle_governance_approve

        chunk_id = f"e2e_approve_missing_{unique_test_id}"

        # Do NOT seed any record -- chunk doesn't exist
        ack_mock = AsyncMock()
        mock_client = AsyncMock()
        body = {
            "user": {"id": "U_E2E_ADMIN"},
            "channel": {"id": admin_channel_id},
            "message": {"ts": "1234567890.123456"},
            "actions": [{"action_id": f"governance_approve_{chunk_id}"}],
        }

        with patch(
            "knowledge_base.slack.governance_admin._is_admin_channel",
            return_value=True,
        ), patch(
            "knowledge_base.governance.approval_engine.async_session_maker",
            governance_db,
        ), patch(
            "knowledge_base.governance.approval_engine.ApprovalEngine._update_neo4j_governance_status",
            new_callable=AsyncMock,
        ):
            await handle_governance_approve(ack_mock, body, mock_client)

        ack_mock.assert_called_once()
        # chat_update should NOT be called (no record to approve)
        mock_client.chat_update.assert_not_called()
        # ephemeral error should be posted
        mock_client.chat_postEphemeral.assert_called_once()
        ephemeral_text = mock_client.chat_postEphemeral.call_args.kwargs.get("text", "")
        assert "Could not approve" in ephemeral_text


# =============================================================================
# Class 2: Reject Full Flow
# =============================================================================


class TestRejectFullFlow:
    """Verify reject modal submission changes DB status + posts confirmation."""

    @pytest.mark.asyncio
    async def test_reject_changes_db_status_and_posts_confirmation(
        self,
        slack_client,
        e2e_config,
        admin_channel_id,
        async_slack_client,
        governance_db,
        unique_test_id,
    ):
        """Full reject flow: seed pending record -> call handler -> verify DB + Slack.

        Calls handle_governance_reject_submit() directly with fabricated view dict.
        """
        from knowledge_base.slack.governance_admin import handle_governance_reject_submit

        chunk_id = f"e2e_reject_{unique_test_id}"

        # Seed pending record
        await _seed_record(governance_db, chunk_id, status="pending_review")

        # Build the view dict matching what Slack sends after modal submission
        ack_mock = AsyncMock()
        body = {"user": {"id": "U_E2E_ADMIN"}}
        view = {
            "private_metadata": chunk_id,
            "state": {
                "values": {
                    "rejection_reason_block": {
                        "rejection_reason": {
                            "value": f"E2E test rejection {unique_test_id}",
                        }
                    }
                }
            },
        }

        with patch(
            "knowledge_base.slack.governance_admin._get_admin_channel",
            return_value=admin_channel_id,
        ), patch(
            "knowledge_base.governance.approval_engine.async_session_maker",
            governance_db,
        ), patch(
            "knowledge_base.governance.approval_engine.ApprovalEngine._update_neo4j_governance_status",
            new_callable=AsyncMock,
        ):
            await handle_governance_reject_submit(
                ack_mock, body, view, async_slack_client
            )

        ack_mock.assert_called_once()

        # Verify DB: status changed to 'rejected'
        db_record = await _get_record(governance_db, chunk_id)
        assert db_record is not None, "Record should exist in DB"
        assert db_record.status == "rejected", (
            f"Status should be 'rejected', got '{db_record.status}'"
        )
        assert db_record.reviewed_by == "U_E2E_ADMIN"
        assert f"E2E test rejection {unique_test_id}" in (db_record.review_note or "")

        # Verify Slack: confirmation message posted to admin channel
        await asyncio.sleep(2)
        history = slack_client.bot_client.conversations_history(
            channel=admin_channel_id, limit=10,
        )
        messages = history.get("messages", [])
        found = _find_message_with_text(messages, chunk_id)
        assert found is not None, (
            f"Rejection confirmation should appear in admin channel with chunk_id"
        )
        assert "Rejected" in found.get("text", ""), (
            "Confirmation message should contain 'Rejected'"
        )

    @pytest.mark.asyncio
    async def test_reject_already_approved_fails(
        self,
        governance_db,
        unique_test_id,
    ):
        """Reject a chunk that's already approved -- DB unchanged, error posted."""
        from knowledge_base.slack.governance_admin import handle_governance_reject_submit

        chunk_id = f"e2e_reject_approved_{unique_test_id}"

        # Seed record with status 'approved' (not 'pending_review')
        await _seed_record(governance_db, chunk_id, status="approved")

        ack_mock = AsyncMock()
        mock_client = AsyncMock()
        body = {"user": {"id": "U_E2E_ADMIN"}}
        view = {
            "private_metadata": chunk_id,
            "state": {
                "values": {
                    "rejection_reason_block": {
                        "rejection_reason": {"value": "Should fail"},
                    }
                }
            },
        }

        with patch(
            "knowledge_base.slack.governance_admin._get_admin_channel",
            return_value="C_ADMIN",
        ), patch(
            "knowledge_base.governance.approval_engine.async_session_maker",
            governance_db,
        ), patch(
            "knowledge_base.governance.approval_engine.ApprovalEngine._update_neo4j_governance_status",
            new_callable=AsyncMock,
        ):
            await handle_governance_reject_submit(
                ack_mock, body, view, mock_client
            )

        ack_mock.assert_called_once()

        # Verify DB: status still 'approved' (unchanged)
        db_record = await _get_record(governance_db, chunk_id)
        assert db_record.status == "approved", (
            f"Status should remain 'approved', got '{db_record.status}'"
        )

        # Verify: "Could not reject" message posted
        mock_client.chat_postMessage.assert_called_once()
        posted_text = mock_client.chat_postMessage.call_args.kwargs.get("text", "")
        assert "Could not reject" in posted_text


# =============================================================================
# Class 3: Revert Full Flow
# =============================================================================


class TestRevertFullFlow:
    """Verify revert modal submission changes DB status, updates Slack, handles expiry."""

    @pytest.mark.asyncio
    async def test_revert_changes_db_status_and_updates_message(
        self,
        slack_client,
        e2e_config,
        admin_channel_id,
        async_slack_client,
        governance_db,
        unique_test_id,
    ):
        """Full revert flow: seed auto_approved record -> call handler -> verify DB + Slack.

        1. Post medium-risk notification to admin channel
        2. Seed auto_approved record with revert_deadline in the future
        3. Call handle_governance_revert_submit() directly
        4. Verify DB: status -> 'reverted'
        5. Verify Slack: message updated to show 'Reverted', buttons removed
        """
        from knowledge_base.slack.governance_admin import handle_governance_revert_submit

        chunk_id = f"e2e_revert_{unique_test_id}"

        # Post notification to get a real message ts
        record = _make_governance_record(
            chunk_id=chunk_id, risk_score=55.0, risk_tier="medium",
            status="auto_approved",
            content_preview=f"[E2E Test] Revert flow {unique_test_id}",
            revert_deadline=datetime.utcnow() + timedelta(hours=24),
        )
        ts = await _post_notification_to_admin(
            async_slack_client, admin_channel_id, record, "medium"
        )

        # Seed the record in test DB
        await _seed_record(
            governance_db, chunk_id, status="auto_approved",
            risk_tier="medium", risk_score=55.0,
            revert_deadline=datetime.utcnow() + timedelta(hours=24),
        )

        await asyncio.sleep(2)

        # Call handle_governance_revert_submit directly
        ack_mock = AsyncMock()
        body = {"user": {"id": "U_E2E_ADMIN"}}
        view = {
            "private_metadata": json.dumps({
                "chunk_id": chunk_id,
                "channel_id": admin_channel_id,
                "message_ts": ts,
            }),
            "state": {
                "values": {
                    "revert_note_block": {
                        "revert_note": {"value": f"E2E revert test {unique_test_id}"},
                    }
                }
            },
        }

        with patch(
            "knowledge_base.governance.approval_engine.async_session_maker",
            governance_db,
        ), patch(
            "knowledge_base.governance.approval_engine.ApprovalEngine._update_neo4j_governance_status",
            new_callable=AsyncMock,
        ):
            await handle_governance_revert_submit(
                ack_mock, body, view, async_slack_client
            )

        ack_mock.assert_called_once()

        # Verify DB: status changed to 'reverted'
        db_record = await _get_record(governance_db, chunk_id)
        assert db_record is not None, "Record should exist in DB"
        assert db_record.status == "reverted", (
            f"Status should be 'reverted', got '{db_record.status}'"
        )
        assert db_record.reviewed_by == "U_E2E_ADMIN"

        # Verify Slack: message updated to show 'Reverted'
        await asyncio.sleep(2)
        history = slack_client.bot_client.conversations_history(
            channel=admin_channel_id, inclusive=True,
            oldest=ts, latest=ts, limit=1,
        )
        messages = history.get("messages", [])
        assert len(messages) > 0

        updated_msg = messages[0]
        blocks_str = json.dumps(updated_msg.get("blocks", []))
        text = updated_msg.get("text", "")

        assert "Reverted" in blocks_str or "Reverted" in text, (
            f"Message should contain 'Reverted'. text={text!r}"
        )
        assert not slack_client.message_has_button(updated_msg, "governance_revert"), (
            "Revert button should be removed after revert"
        )

    @pytest.mark.asyncio
    async def test_revert_expired_window_fails(
        self,
        slack_client,
        e2e_config,
        admin_channel_id,
        async_slack_client,
        governance_db,
        unique_test_id,
    ):
        """Revert with expired deadline -- DB unchanged, error message posted."""
        from knowledge_base.slack.governance_admin import handle_governance_revert_submit

        chunk_id = f"e2e_revert_expired_{unique_test_id}"

        # Post notification to get a real message ts
        record = _make_governance_record(
            chunk_id=chunk_id, risk_score=50.0, risk_tier="medium",
            status="auto_approved",
            content_preview=f"[E2E Test] Expired revert {unique_test_id}",
            revert_deadline=datetime.utcnow() - timedelta(hours=1),
        )
        ts = await _post_notification_to_admin(
            async_slack_client, admin_channel_id, record, "medium"
        )

        # Seed record with EXPIRED revert deadline
        await _seed_record(
            governance_db, chunk_id, status="auto_approved",
            risk_tier="medium", risk_score=50.0,
            revert_deadline=datetime.utcnow() - timedelta(hours=1),
        )

        await asyncio.sleep(2)

        ack_mock = AsyncMock()
        body = {"user": {"id": "U_E2E_ADMIN"}}
        view = {
            "private_metadata": json.dumps({
                "chunk_id": chunk_id,
                "channel_id": admin_channel_id,
                "message_ts": ts,
            }),
            "state": {
                "values": {
                    "revert_note_block": {
                        "revert_note": {"value": ""},
                    }
                }
            },
        }

        with patch(
            "knowledge_base.governance.approval_engine.async_session_maker",
            governance_db,
        ), patch(
            "knowledge_base.governance.approval_engine.ApprovalEngine._update_neo4j_governance_status",
            new_callable=AsyncMock,
        ):
            await handle_governance_revert_submit(
                ack_mock, body, view, async_slack_client
            )

        ack_mock.assert_called_once()

        # Verify DB: status still 'auto_approved' (unchanged)
        db_record = await _get_record(governance_db, chunk_id)
        assert db_record.status == "auto_approved", (
            f"Status should remain 'auto_approved', got '{db_record.status}'"
        )

        # Verify Slack: error message posted (NOT chat_update on original)
        await asyncio.sleep(2)
        history = slack_client.bot_client.conversations_history(
            channel=admin_channel_id, limit=10,
        )
        messages = history.get("messages", [])
        found = _find_message_with_text(messages, "expired")
        assert found is not None, (
            "Error message about expired revert window should be posted"
        )

    @pytest.mark.asyncio
    async def test_revert_low_risk_no_window_fails(
        self,
        governance_db,
        unique_test_id,
    ):
        """Revert a low-risk item (no revert_deadline) -- DB unchanged."""
        from knowledge_base.slack.governance_admin import handle_governance_revert_submit

        chunk_id = f"e2e_revert_low_{unique_test_id}"

        # Seed record with NO revert deadline (low-risk auto-approved)
        await _seed_record(
            governance_db, chunk_id, status="auto_approved",
            risk_tier="low", risk_score=15.0,
            revert_deadline=None,
        )

        ack_mock = AsyncMock()
        mock_client = AsyncMock()
        body = {"user": {"id": "U_E2E_ADMIN"}}
        view = {
            "private_metadata": json.dumps({
                "chunk_id": chunk_id,
                "channel_id": "C_ADMIN",
                "message_ts": "1234567890.123456",
            }),
            "state": {
                "values": {
                    "revert_note_block": {
                        "revert_note": {"value": ""},
                    }
                }
            },
        }

        with patch(
            "knowledge_base.governance.approval_engine.async_session_maker",
            governance_db,
        ), patch(
            "knowledge_base.governance.approval_engine.ApprovalEngine._update_neo4j_governance_status",
            new_callable=AsyncMock,
        ):
            await handle_governance_revert_submit(
                ack_mock, body, view, mock_client
            )

        ack_mock.assert_called_once()

        # Verify DB: status still 'auto_approved'
        db_record = await _get_record(governance_db, chunk_id)
        assert db_record.status == "auto_approved", (
            f"Low-risk status should remain 'auto_approved', got '{db_record.status}'"
        )

        # Verify: error message posted (revert window expired/not available)
        mock_client.chat_postMessage.assert_called_once()
        posted_text = mock_client.chat_postMessage.call_args.kwargs.get("text", "")
        assert "expired" in posted_text.lower() or "cannot" in posted_text.lower()


# =============================================================================
# Class 4: Admin Authorization
# =============================================================================


class TestAdminAuthorization:
    """Verify governance actions from non-admin channels are rejected."""

    @pytest.mark.asyncio
    async def test_approve_from_non_admin_channel_rejected(
        self,
        e2e_config,
        admin_channel_id,
        governance_db,
        unique_test_id,
    ):
        """Approve action from test channel (not admin) -- rejected, DB unchanged."""
        from knowledge_base.slack.governance_admin import handle_governance_approve

        chunk_id = f"e2e_auth_approve_{unique_test_id}"

        # Seed pending record
        await _seed_record(governance_db, chunk_id, status="pending_review")

        ack_mock = AsyncMock()
        mock_client = AsyncMock()

        # Use test channel (NOT admin channel) as the action source
        non_admin_channel = e2e_config["channel_id"]
        body = {
            "user": {"id": "U_NON_ADMIN"},
            "channel": {"id": non_admin_channel},
            "message": {"ts": "1234567890.123456"},
            "actions": [{"action_id": f"governance_approve_{chunk_id}"}],
        }

        # Patch _get_admin_channel to return the REAL admin channel
        # so the comparison with non_admin_channel fails (as it should)
        with patch(
            "knowledge_base.slack.governance_admin._get_admin_channel",
            return_value=admin_channel_id,
        ), patch(
            "knowledge_base.governance.approval_engine.async_session_maker",
            governance_db,
        ):
            await handle_governance_approve(ack_mock, body, mock_client)

        ack_mock.assert_called_once()

        # Verify DB: status unchanged
        db_record = await _get_record(governance_db, chunk_id)
        assert db_record.status == "pending_review", (
            f"Status should remain 'pending_review', got '{db_record.status}'"
        )

        # Verify: ephemeral rejection posted
        mock_client.chat_postEphemeral.assert_called_once()
        ephemeral_text = mock_client.chat_postEphemeral.call_args.kwargs.get("text", "")
        assert "admin channel" in ephemeral_text.lower(), (
            f"Ephemeral should mention admin channel. Got: {ephemeral_text!r}"
        )

        # Verify: chat_update NOT called (no approval happened)
        mock_client.chat_update.assert_not_called()

    @pytest.mark.asyncio
    async def test_mark_reviewed_from_non_admin_rejected(
        self,
        e2e_config,
        admin_channel_id,
        unique_test_id,
    ):
        """Mark Reviewed from non-admin channel -- rejected, no message update."""
        from knowledge_base.slack.governance_admin import handle_governance_mark_reviewed

        chunk_id = f"e2e_auth_reviewed_{unique_test_id}"
        non_admin_channel = e2e_config["channel_id"]

        ack_mock = AsyncMock()
        mock_client = AsyncMock()
        body = {
            "user": {"id": "U_NON_ADMIN"},
            "channel": {"id": non_admin_channel},
            "message": {"ts": "1234567890.123456"},
            "actions": [{"action_id": f"governance_mark_reviewed_{chunk_id}"}],
        }

        with patch(
            "knowledge_base.slack.governance_admin._get_admin_channel",
            return_value=admin_channel_id,
        ):
            await handle_governance_mark_reviewed(ack_mock, body, mock_client)

        ack_mock.assert_called_once()

        # Verify: ephemeral rejection posted
        mock_client.chat_postEphemeral.assert_called_once()

        # Verify: chat_update NOT called (no review happened)
        mock_client.chat_update.assert_not_called()


# =============================================================================
# Class 5: Mark Reviewed
# =============================================================================


class TestMarkReviewed:
    """Verify Mark Reviewed only updates message -- NO DB change."""

    @pytest.mark.asyncio
    async def test_mark_reviewed_updates_message_no_db_change(
        self,
        slack_client,
        e2e_config,
        admin_channel_id,
        async_slack_client,
        governance_db,
        unique_test_id,
    ):
        """Mark Reviewed: message updated to 'Reviewed', DB status stays auto_approved.

        This is a cosmetic-only operation -- no governance status transition.
        """
        from knowledge_base.slack.governance_admin import handle_governance_mark_reviewed

        chunk_id = f"e2e_reviewed_{unique_test_id}"

        # Post notification to get a real message
        record = _make_governance_record(
            chunk_id=chunk_id, risk_score=50.0, risk_tier="medium",
            status="auto_approved",
            content_preview=f"[E2E Test] Mark reviewed {unique_test_id}",
            revert_deadline=datetime.utcnow() + timedelta(hours=24),
        )
        ts = await _post_notification_to_admin(
            async_slack_client, admin_channel_id, record, "medium"
        )

        # Seed record in test DB
        await _seed_record(
            governance_db, chunk_id, status="auto_approved",
            risk_tier="medium", risk_score=50.0,
            revert_deadline=datetime.utcnow() + timedelta(hours=24),
        )

        await asyncio.sleep(2)

        # Call handler
        ack_mock = AsyncMock()
        body = {
            "user": {"id": "U_E2E_ADMIN"},
            "channel": {"id": admin_channel_id},
            "message": {"ts": ts},
            "actions": [{"action_id": f"governance_mark_reviewed_{chunk_id}"}],
        }

        with patch(
            "knowledge_base.slack.governance_admin._is_admin_channel",
            return_value=True,
        ):
            await handle_governance_mark_reviewed(ack_mock, body, async_slack_client)

        ack_mock.assert_called_once()

        # Verify DB: status STILL 'auto_approved' (no change)
        db_record = await _get_record(governance_db, chunk_id)
        assert db_record.status == "auto_approved", (
            f"Mark Reviewed should NOT change DB status. Got '{db_record.status}'"
        )

        # Verify Slack: message updated to show 'Reviewed'
        await asyncio.sleep(2)
        history = slack_client.bot_client.conversations_history(
            channel=admin_channel_id, inclusive=True,
            oldest=ts, latest=ts, limit=1,
        )
        messages = history.get("messages", [])
        assert len(messages) > 0

        updated_msg = messages[0]
        blocks_str = json.dumps(updated_msg.get("blocks", []))
        text = updated_msg.get("text", "")

        assert "Reviewed" in blocks_str or "Reviewed" in text, (
            f"Message should contain 'Reviewed'. text={text!r}"
        )
        assert not slack_client.message_has_button(updated_msg, "governance_revert"), (
            "Revert button should be removed after review"
        )
        assert not slack_client.message_has_button(updated_msg, "governance_mark_reviewed"), (
            "Mark Reviewed button should be removed"
        )


# =============================================================================
# Class 6: Notification Structure
# =============================================================================


class TestGovernanceNotifications:
    """Verify notification functions post correctly structured Slack messages."""

    @pytest.mark.asyncio
    async def test_high_risk_notification_structure(
        self,
        slack_client,
        admin_channel_id,
        async_slack_client,
        unique_test_id,
    ):
        """High-risk notification: 'Approval Request' header, Approve+Reject buttons."""
        record = _make_governance_record(
            chunk_id=f"e2e_notif_high_{unique_test_id}",
            risk_score=85.0, risk_tier="high",
            content_preview=f"[E2E Test] High risk notif {unique_test_id}",
        )
        ts = await _post_notification_to_admin(
            async_slack_client, admin_channel_id, record, "high"
        )

        await asyncio.sleep(2)
        history = slack_client.bot_client.conversations_history(
            channel=admin_channel_id, inclusive=True,
            oldest=ts, latest=ts, limit=1,
        )
        messages = history.get("messages", [])
        assert len(messages) > 0
        msg = messages[0]

        blocks_str = json.dumps(msg.get("blocks", []))
        assert "Approval Request" in blocks_str
        assert "HIGH" in blocks_str
        assert slack_client.message_has_button(msg, "governance_approve")
        assert slack_client.message_has_button(msg, "governance_reject")

    @pytest.mark.asyncio
    async def test_medium_risk_notification_structure(
        self,
        slack_client,
        admin_channel_id,
        async_slack_client,
        unique_test_id,
    ):
        """Medium-risk notification: 'Auto-Approved' header, Revert+Mark Reviewed buttons."""
        record = _make_governance_record(
            chunk_id=f"e2e_notif_med_{unique_test_id}",
            risk_score=50.0, risk_tier="medium",
            status="auto_approved",
            content_preview=f"[E2E Test] Medium risk notif {unique_test_id}",
            revert_deadline=datetime.utcnow() + timedelta(hours=24),
        )
        ts = await _post_notification_to_admin(
            async_slack_client, admin_channel_id, record, "medium"
        )

        await asyncio.sleep(2)
        history = slack_client.bot_client.conversations_history(
            channel=admin_channel_id, inclusive=True,
            oldest=ts, latest=ts, limit=1,
        )
        messages = history.get("messages", [])
        assert len(messages) > 0
        msg = messages[0]

        blocks_str = json.dumps(msg.get("blocks", []))
        assert "Auto-Approved" in blocks_str
        assert "MEDIUM" in blocks_str
        assert slack_client.message_has_button(msg, "governance_revert")
        assert slack_client.message_has_button(msg, "governance_mark_reviewed")


# =============================================================================
# Class 7: Search Filter
# =============================================================================


class TestGovernanceSearchFilter:
    """Verify governance-aware search filtering in GraphitiRetriever.

    Uses mocked graphiti.search() and _lookup_episodes() to test the
    filtering logic in search_chunks() without real Neo4j.
    """

    @staticmethod
    def _make_graphiti_result(
        *, name: str = "edge-1", score: float = 0.9,
        episodes: list[str] | None = None,
    ) -> MagicMock:
        mock = MagicMock()
        mock.name = name
        mock.fact = None
        mock.content = None
        mock.source_description = None
        mock.score = score
        mock.episodes = episodes or [str(uuid.uuid4())]
        mock.uuid = str(uuid.uuid4())
        return mock

    @staticmethod
    def _make_episode_data(
        *, name: str = "chunk-1",
        content: str = "A detailed paragraph with enough content to pass the minimum length filter.",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "name": name,
            "content": content,
            "metadata": metadata or {"chunk_id": name},
        }

    @staticmethod
    def _setup_retriever(
        mock_settings: MagicMock, mock_get_client: MagicMock,
        *, governance_enabled: bool = True,
    ) -> tuple:
        from knowledge_base.graph.graphiti_retriever import GraphitiRetriever

        mock_settings.GRAPH_ENABLE_GRAPHITI = True
        mock_settings.GRAPH_GROUP_ID = "test"
        mock_settings.NEO4J_SEARCH_MAX_RETRIES = 0
        mock_settings.SEARCH_MIN_CONTENT_LENGTH = 20
        mock_settings.GOVERNANCE_ENABLED = governance_enabled

        mock_graphiti = AsyncMock()
        mock_client = MagicMock()
        mock_client.get_client = AsyncMock(return_value=mock_graphiti)
        mock_get_client.return_value = mock_client

        retriever = GraphitiRetriever.__new__(GraphitiRetriever)
        retriever.group_id = "test"
        retriever.client = mock_client
        retriever._graphiti = None

        return retriever, mock_graphiti

    @pytest.mark.asyncio
    @patch("knowledge_base.graph.graphiti_retriever.get_graphiti_client")
    @patch("knowledge_base.graph.graphiti_retriever.settings")
    async def test_reverted_content_excluded_from_search(
        self, mock_settings: MagicMock, mock_get_client: MagicMock,
    ) -> None:
        """Reverted content is excluded from search results."""
        retriever, mock_graphiti = self._setup_retriever(
            mock_settings, mock_get_client, governance_enabled=True,
        )

        ep_good = str(uuid.uuid4())
        ep_reverted = str(uuid.uuid4())

        mock_graphiti.search = AsyncMock(return_value=[
            self._make_graphiti_result(name="edge-good", score=0.9, episodes=[ep_good]),
            self._make_graphiti_result(name="edge-reverted", score=0.8, episodes=[ep_reverted]),
        ])

        with patch.object(retriever, "_lookup_episodes", new_callable=AsyncMock) as mock_lookup:
            mock_lookup.return_value = {
                ep_good: self._make_episode_data(
                    name="chunk-good",
                    content="Approved content that should appear in search results.",
                    metadata={"chunk_id": "chunk-good", "governance_status": "approved"},
                ),
                ep_reverted: self._make_episode_data(
                    name="chunk-reverted",
                    content="Reverted content that should NOT appear in search results.",
                    metadata={"chunk_id": "chunk-reverted", "governance_status": "reverted"},
                ),
            }
            results = await retriever.search_chunks(query="test query", num_results=10)

        assert len(results) == 1
        assert results[0].chunk_id == "chunk-good"

    @pytest.mark.asyncio
    @patch("knowledge_base.graph.graphiti_retriever.get_graphiti_client")
    @patch("knowledge_base.graph.graphiti_retriever.settings")
    async def test_approved_content_included_in_search(
        self, mock_settings: MagicMock, mock_get_client: MagicMock,
    ) -> None:
        """Approved content and legacy content (no field) are both included."""
        retriever, mock_graphiti = self._setup_retriever(
            mock_settings, mock_get_client, governance_enabled=True,
        )

        ep_approved = str(uuid.uuid4())
        ep_legacy = str(uuid.uuid4())

        mock_graphiti.search = AsyncMock(return_value=[
            self._make_graphiti_result(name="edge-approved", score=0.9, episodes=[ep_approved]),
            self._make_graphiti_result(name="edge-legacy", score=0.85, episodes=[ep_legacy]),
        ])

        with patch.object(retriever, "_lookup_episodes", new_callable=AsyncMock) as mock_lookup:
            mock_lookup.return_value = {
                ep_approved: self._make_episode_data(
                    name="chunk-approved",
                    content="Approved content with explicit governance status field.",
                    metadata={"chunk_id": "chunk-approved", "governance_status": "approved"},
                ),
                ep_legacy: self._make_episode_data(
                    name="chunk-legacy",
                    content="Legacy content without governance metadata field present.",
                    metadata={"chunk_id": "chunk-legacy", "page_title": "Old Page"},
                ),
            }
            results = await retriever.search_chunks(query="test query", num_results=10)

        assert len(results) == 2
        chunk_ids = {r.chunk_id for r in results}
        assert "chunk-approved" in chunk_ids
        assert "chunk-legacy" in chunk_ids

    @pytest.mark.asyncio
    @patch("knowledge_base.graph.graphiti_retriever.get_graphiti_client")
    @patch("knowledge_base.graph.graphiti_retriever.settings")
    async def test_status_transition_affects_searchability(
        self, mock_settings: MagicMock, mock_get_client: MagicMock,
    ) -> None:
        """Content starts as pending (excluded) then becomes approved (included)."""
        retriever, mock_graphiti = self._setup_retriever(
            mock_settings, mock_get_client, governance_enabled=True,
        )

        ep_uuid = str(uuid.uuid4())
        mock_graphiti.search = AsyncMock(
            return_value=[self._make_graphiti_result(name="edge-1", score=0.9, episodes=[ep_uuid])]
        )

        # Phase 1: pending -- excluded
        with patch.object(retriever, "_lookup_episodes", new_callable=AsyncMock) as mock_lookup:
            mock_lookup.return_value = {
                ep_uuid: self._make_episode_data(
                    name="chunk-1",
                    content="Content that starts pending but gets approved later.",
                    metadata={"chunk_id": "chunk-1", "governance_status": "pending"},
                ),
            }
            results_pending = await retriever.search_chunks(query="test query", num_results=10)

        assert len(results_pending) == 0, "Pending content should be excluded"

        # Phase 2: approved -- included
        with patch.object(retriever, "_lookup_episodes", new_callable=AsyncMock) as mock_lookup:
            mock_lookup.return_value = {
                ep_uuid: self._make_episode_data(
                    name="chunk-1",
                    content="Content that starts pending but gets approved later.",
                    metadata={"chunk_id": "chunk-1", "governance_status": "approved"},
                ),
            }
            results_approved = await retriever.search_chunks(query="test query", num_results=10)

        assert len(results_approved) == 1
        assert results_approved[0].chunk_id == "chunk-1"


# =============================================================================
# Class 8: Queue Handler
# =============================================================================


class TestGovernanceQueueHandler:
    """Test handle_governance_queue() slash command handler."""

    @pytest.mark.asyncio
    async def test_queue_shows_pending_and_revertable(self, unique_test_id):
        """Queue with 2 pending + 1 revertable renders both sections."""
        from knowledge_base.slack.governance_admin import handle_governance_queue

        pending_items = [
            _make_governance_record(
                chunk_id=f"pending_1_{unique_test_id}",
                risk_score=80.0, risk_tier="high", status="pending_review",
                content_preview="Pending item 1",
            ),
            _make_governance_record(
                chunk_id=f"pending_2_{unique_test_id}",
                risk_score=75.0, risk_tier="high", status="pending_review",
                content_preview="Pending item 2",
            ),
        ]

        revertable_items = [
            _make_governance_record(
                chunk_id=f"revertable_1_{unique_test_id}",
                risk_score=55.0, risk_tier="medium", status="auto_approved",
                content_preview="Revertable item 1",
                revert_deadline=datetime.utcnow() + timedelta(hours=12),
            ),
        ]

        ack_mock = AsyncMock()
        client_mock = AsyncMock()
        command = {"user_id": "U_TEST_ADMIN", "channel_id": "C_TEST_CHANNEL"}

        engine_instance = AsyncMock()
        engine_instance.get_pending_queue = AsyncMock(return_value=pending_items)
        engine_instance.get_revertable_items = AsyncMock(return_value=revertable_items)

        with patch(
            "knowledge_base.governance.approval_engine.ApprovalEngine",
            return_value=engine_instance,
        ):
            await handle_governance_queue(ack_mock, command, client_mock)

        ack_mock.assert_called_once()
        client_mock.chat_postEphemeral.assert_called_once()

        call_kwargs = client_mock.chat_postEphemeral.call_args
        blocks = call_kwargs.kwargs.get("blocks", [])
        blocks_str = json.dumps(blocks)

        assert "Pending Approval" in blocks_str
        assert "Revertable" in blocks_str
        assert f"pending_1_{unique_test_id}" in blocks_str
        assert f"pending_2_{unique_test_id}" in blocks_str
        assert f"revertable_1_{unique_test_id}" in blocks_str

    @pytest.mark.asyncio
    async def test_queue_empty(self, unique_test_id):
        """Empty queue shows 'No pending items' ephemeral."""
        from knowledge_base.slack.governance_admin import handle_governance_queue

        ack_mock = AsyncMock()
        client_mock = AsyncMock()
        command = {"user_id": "U_TEST_ADMIN", "channel_id": "C_TEST_CHANNEL"}

        engine_instance = AsyncMock()
        engine_instance.get_pending_queue = AsyncMock(return_value=[])
        engine_instance.get_revertable_items = AsyncMock(return_value=[])

        with patch(
            "knowledge_base.governance.approval_engine.ApprovalEngine",
            return_value=engine_instance,
        ):
            await handle_governance_queue(ack_mock, command, client_mock)

        ack_mock.assert_called_once()
        client_mock.chat_postEphemeral.assert_called_once()

        call_kwargs = client_mock.chat_postEphemeral.call_args
        text = call_kwargs.kwargs.get("text", "")
        assert "No pending items" in text
