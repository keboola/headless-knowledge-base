"""E2E tests for knowledge governance admin workflows.

Tests verify:
1. Governance notifications appear in admin channel with correct structure
2. Admin button clicks (Approve, Reject, Mark Reviewed) work through staging bot
3. Governance queue handler returns correct data

Prerequisites:
- E2E_ADMIN_CHANNEL set to admin channel ID (bot must be a member)
- GOVERNANCE_ENABLED=true on staging
- SLACK_STAGING_SIGNING_SECRET for button click tests
"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from knowledge_base.config import settings
from knowledge_base.db.models import KnowledgeGovernanceRecord

logger = logging.getLogger(__name__)
pytestmark = pytest.mark.e2e


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def has_signing_secret():
    """Check if signing secret is available for button click tests."""
    if not (
        os.environ.get("SLACK_STAGING_SIGNING_SECRET")
        or os.environ.get("SLACK_SIGNING_SECRET")
    ):
        pytest.skip(
            "SLACK_STAGING_SIGNING_SECRET or SLACK_SIGNING_SECRET not set. "
            "Fetch from Secret Manager or set in .env.e2e"
        )
    return True


@pytest.fixture
def has_governance():
    """Skip if governance is not enabled."""
    if not settings.GOVERNANCE_ENABLED:
        pytest.skip("GOVERNANCE_ENABLED is False")
    return True


@pytest.fixture
def governance_record(unique_test_id):
    """Create a fabricated KnowledgeGovernanceRecord for testing."""
    # This creates an in-memory record (not persisted to DB)
    record = KnowledgeGovernanceRecord(
        chunk_id=f"e2e_gov_{unique_test_id}",
        risk_score=72.0,
        risk_tier="high",
        risk_factors=json.dumps({
            "author_trust": 80.0,
            "source_type": 70.0,
            "content_scope": 55.0,
            "novelty": 20.0,
            "contradiction": 20.0,
        }),
        intake_path="slack_ingest",
        submitted_by="e2e_test_user",
        submitted_at=datetime.utcnow(),
        content_preview=(
            f"E2E test content {unique_test_id} - this is fabricated "
            "high-risk content for testing governance workflows"
        ),
        status="pending_review",
        revert_deadline=None,
    )
    return record


@pytest.fixture
def medium_risk_record(unique_test_id):
    """Create a fabricated medium-risk record."""
    record = KnowledgeGovernanceRecord(
        chunk_id=f"e2e_gov_med_{unique_test_id}",
        risk_score=45.0,
        risk_tier="medium",
        risk_factors=json.dumps({
            "author_trust": 60.0,
            "source_type": 30.0,
            "content_scope": 35.0,
            "novelty": 20.0,
            "contradiction": 20.0,
        }),
        intake_path="slack_create",
        submitted_by="e2e_test_user",
        submitted_at=datetime.utcnow(),
        content_preview=(
            f"E2E test content {unique_test_id} - medium risk "
            "auto-approved with revert window"
        ),
        status="auto_approved",
        revert_deadline=datetime.utcnow() + timedelta(hours=24),
    )
    return record


def _mock_async_session_maker():
    """Create a mock async_session_maker that supports async context manager.

    The notify_admin_* functions do a lazy import of async_session_maker and use
    it as: ``async with async_session_maker() as session: ...``
    This mock replaces the source module attribute so the lazy import picks it up.
    """
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )
    mock_session.commit = AsyncMock()

    @asynccontextmanager
    async def _session_ctx():
        yield mock_session

    mock_maker = MagicMock(side_effect=lambda: _session_ctx())
    return mock_maker


# =============================================================================
# Class 1: Medium-Risk Notifications
# =============================================================================


class TestGovernanceMediumRiskNotification:
    """Test medium-risk governance notifications in admin channel."""

    @pytest.mark.asyncio
    async def test_medium_risk_posts_to_admin_channel(
        self,
        slack_client,
        e2e_config,
        admin_channel_id,
        medium_risk_record,
        unique_test_id,
    ):
        """Verify medium-risk notification appears in admin channel with correct structure."""
        from slack_sdk.web.async_client import AsyncWebClient

        from knowledge_base.slack.governance_admin import notify_admin_medium_risk

        async_client = AsyncWebClient(token=e2e_config["bot_token"])

        # Patch the admin channel to use our test channel and mock DB
        # (record is in-memory only -- lazy import reads from source module)
        with patch(
            "knowledge_base.slack.governance_admin._get_admin_channel",
            return_value=admin_channel_id,
        ):
            with patch(
                "knowledge_base.db.database.async_session_maker",
                new=_mock_async_session_maker(),
            ):
                ts = await notify_admin_medium_risk(async_client, medium_risk_record)

        assert ts is not None, "notify_admin_medium_risk should return message timestamp"

        # Wait for message to be visible
        await asyncio.sleep(2)

        # Fetch the message
        history = slack_client.bot_client.conversations_history(
            channel=admin_channel_id,
            inclusive=True,
            oldest=ts,
            latest=ts,
            limit=1,
        ).get("messages", [])

        assert len(history) > 0, f"Medium-risk notification not found at ts={ts}"
        msg = history[0]

        # Verify message structure
        blocks_text = slack_client._extract_text_from_blocks(msg.get("blocks", []))
        assert (
            "auto-approved" in blocks_text.lower()
            or "review window" in blocks_text.lower()
        ), f"Should mention auto-approved or review window. Got: {blocks_text[:200]}"

        # Verify buttons
        assert slack_client.message_has_button(
            msg, "governance_revert"
        ), "Medium-risk notification should have Revert button"
        assert slack_client.message_has_button(
            msg, "governance_mark_reviewed"
        ), "Medium-risk notification should have Mark Reviewed button"

        # Verify risk info
        assert str(int(medium_risk_record.risk_score)) in blocks_text, (
            "Should show risk score"
        )

    @pytest.mark.asyncio
    async def test_mark_reviewed_button_click_succeeds(
        self,
        slack_client,
        e2e_config,
        admin_channel_id,
        medium_risk_record,
        has_signing_secret,
        unique_test_id,
    ):
        """Verify Mark Reviewed button click returns 200 and updates message."""
        from slack_sdk.web.async_client import AsyncWebClient

        from knowledge_base.slack.governance_admin import notify_admin_medium_risk

        async_client = AsyncWebClient(token=e2e_config["bot_token"])

        # Post notification
        with patch(
            "knowledge_base.slack.governance_admin._get_admin_channel",
            return_value=admin_channel_id,
        ):
            with patch(
                "knowledge_base.db.database.async_session_maker",
                new=_mock_async_session_maker(),
            ):
                ts = await notify_admin_medium_risk(async_client, medium_risk_record)

        assert ts is not None

        await asyncio.sleep(2)

        # Fetch the notification message
        history = slack_client.bot_client.conversations_history(
            channel=admin_channel_id,
            inclusive=True,
            oldest=ts,
            latest=ts,
            limit=1,
        ).get("messages", [])
        assert len(history) > 0
        msg = history[0]

        # Click Mark Reviewed button
        success = await slack_client.click_button(
            msg,
            "governance_mark_reviewed",
            channel_id=admin_channel_id,
        )
        assert success, "Mark Reviewed button click should return 200"

        # Wait for message update
        await asyncio.sleep(3)

        # Verify message was updated
        updated = slack_client.bot_client.conversations_history(
            channel=admin_channel_id,
            inclusive=True,
            oldest=ts,
            latest=ts,
            limit=1,
        ).get("messages", [])

        if updated:
            updated_text = slack_client._extract_text_from_blocks(
                updated[0].get("blocks", [])
            )
            assert "reviewed" in updated_text.lower(), (
                f"Message should show 'Reviewed' after click. Got: {updated_text[:200]}"
            )


# =============================================================================
# Class 2: High-Risk Notifications
# =============================================================================


class TestGovernanceHighRiskNotification:
    """Test high-risk governance notifications and admin actions."""

    @pytest.mark.asyncio
    async def test_high_risk_posts_to_admin_channel(
        self,
        slack_client,
        e2e_config,
        admin_channel_id,
        governance_record,
        unique_test_id,
    ):
        """Verify high-risk notification appears with Approve/Reject buttons."""
        from slack_sdk.web.async_client import AsyncWebClient

        from knowledge_base.slack.governance_admin import notify_admin_high_risk

        async_client = AsyncWebClient(token=e2e_config["bot_token"])

        with patch(
            "knowledge_base.slack.governance_admin._get_admin_channel",
            return_value=admin_channel_id,
        ):
            with patch(
                "knowledge_base.db.database.async_session_maker",
                new=_mock_async_session_maker(),
            ):
                ts = await notify_admin_high_risk(async_client, governance_record)

        assert ts is not None, "notify_admin_high_risk should return message timestamp"

        await asyncio.sleep(2)

        history = slack_client.bot_client.conversations_history(
            channel=admin_channel_id,
            inclusive=True,
            oldest=ts,
            latest=ts,
            limit=1,
        ).get("messages", [])

        assert len(history) > 0, f"High-risk notification not found at ts={ts}"
        msg = history[0]

        blocks_text = slack_client._extract_text_from_blocks(msg.get("blocks", []))

        # Verify "Approval Request" header
        assert "approval request" in blocks_text.lower(), (
            f"Should contain 'Approval Request'. Got: {blocks_text[:200]}"
        )

        # Verify buttons
        assert slack_client.message_has_button(
            msg, "governance_approve"
        ), "High-risk notification should have Approve button"
        assert slack_client.message_has_button(
            msg, "governance_reject"
        ), "High-risk notification should have Reject button"

        # Verify risk info
        assert "HIGH" in blocks_text, "Should show HIGH risk tier"
        assert str(int(governance_record.risk_score)) in blocks_text, (
            "Should show risk score"
        )

    @pytest.mark.asyncio
    async def test_approve_button_click_succeeds(
        self,
        slack_client,
        e2e_config,
        admin_channel_id,
        governance_record,
        has_signing_secret,
        unique_test_id,
    ):
        """Verify Approve button click returns 200."""
        from slack_sdk.web.async_client import AsyncWebClient

        from knowledge_base.slack.governance_admin import notify_admin_high_risk

        async_client = AsyncWebClient(token=e2e_config["bot_token"])

        # Post notification
        with patch(
            "knowledge_base.slack.governance_admin._get_admin_channel",
            return_value=admin_channel_id,
        ):
            with patch(
                "knowledge_base.db.database.async_session_maker",
                new=_mock_async_session_maker(),
            ):
                ts = await notify_admin_high_risk(async_client, governance_record)

        assert ts is not None

        await asyncio.sleep(2)

        history = slack_client.bot_client.conversations_history(
            channel=admin_channel_id,
            inclusive=True,
            oldest=ts,
            latest=ts,
            limit=1,
        ).get("messages", [])
        assert len(history) > 0
        msg = history[0]

        # Click Approve button (will call ApprovalEngine.approve which may fail since
        # we don't have a real DB record - but the button handler should still return 200)
        success = await slack_client.click_button(
            msg,
            "governance_approve",
            channel_id=admin_channel_id,
        )
        assert success, (
            "Approve button click should return 200 "
            "(handler processed without HTTP error)"
        )

    @pytest.mark.asyncio
    async def test_reject_button_click_succeeds(
        self,
        slack_client,
        e2e_config,
        admin_channel_id,
        governance_record,
        has_signing_secret,
        unique_test_id,
    ):
        """Verify Reject button click returns 200 (opens modal)."""
        from slack_sdk.web.async_client import AsyncWebClient

        from knowledge_base.slack.governance_admin import notify_admin_high_risk

        async_client = AsyncWebClient(token=e2e_config["bot_token"])

        with patch(
            "knowledge_base.slack.governance_admin._get_admin_channel",
            return_value=admin_channel_id,
        ):
            with patch(
                "knowledge_base.db.database.async_session_maker",
                new=_mock_async_session_maker(),
            ):
                ts = await notify_admin_high_risk(async_client, governance_record)

        assert ts is not None

        await asyncio.sleep(2)

        history = slack_client.bot_client.conversations_history(
            channel=admin_channel_id,
            inclusive=True,
            oldest=ts,
            latest=ts,
            limit=1,
        ).get("messages", [])
        assert len(history) > 0
        msg = history[0]

        # Click Reject button (opens modal -- 200 means handler ran successfully)
        success = await slack_client.click_button(
            msg,
            "governance_reject",
            channel_id=admin_channel_id,
        )
        assert success, "Reject button click should return 200 (modal opens)"


# =============================================================================
# Class 3: Governance Queue Handler
# =============================================================================


class TestGovernanceQueueHandler:
    """Test /governance-queue command handler directly.

    Ephemeral responses can't be verified via Slack API, so we test
    the handler with mocked ack and verify chat_postEphemeral calls.
    """

    @pytest.mark.asyncio
    async def test_governance_queue_empty(
        self, e2e_config, admin_channel_id, has_governance
    ):
        """Verify empty queue returns 'No pending items' message."""
        from slack_sdk.web.async_client import AsyncWebClient

        from knowledge_base.slack.governance_admin import handle_governance_queue

        ack = AsyncMock()
        client = AsyncMock(spec=AsyncWebClient)

        command = {
            "user_id": "U_E2E_TEST",
            "channel_id": admin_channel_id,
        }

        # Patch at the source module since handle_governance_queue uses a lazy import
        with patch(
            "knowledge_base.governance.approval_engine.ApprovalEngine"
        ) as MockEngine:
            engine_instance = AsyncMock()
            engine_instance.get_pending_queue.return_value = []
            engine_instance.get_revertable_items.return_value = []
            engine_instance._ensure_table = AsyncMock()
            MockEngine.return_value = engine_instance

            await handle_governance_queue(ack, command, client)

        ack.assert_called_once()
        client.chat_postEphemeral.assert_called_once()
        call_kwargs = client.chat_postEphemeral.call_args
        assert (
            "no pending items" in call_kwargs.kwargs.get("text", "").lower()
            or "no pending items" in str(call_kwargs).lower()
        ), f"Should say 'No pending items'. Got: {call_kwargs}"

    @pytest.mark.asyncio
    async def test_governance_queue_with_pending_items(
        self,
        e2e_config,
        admin_channel_id,
        has_governance,
        unique_test_id,
    ):
        """Verify queue with items shows them with Approve/Reject buttons."""
        from slack_sdk.web.async_client import AsyncWebClient

        from knowledge_base.slack.governance_admin import handle_governance_queue

        ack = AsyncMock()
        client = AsyncMock(spec=AsyncWebClient)

        command = {
            "user_id": "U_E2E_TEST",
            "channel_id": admin_channel_id,
        }

        # Create fabricated pending records
        pending_1 = KnowledgeGovernanceRecord(
            chunk_id=f"pending_1_{unique_test_id}",
            risk_score=75.0,
            risk_tier="high",
            risk_factors="{}",
            content_preview="First pending item content",
            submitted_by="test_user",
            intake_path="slack_ingest",
            submitted_at=datetime.utcnow(),
            status="pending_review",
        )

        pending_2 = KnowledgeGovernanceRecord(
            chunk_id=f"pending_2_{unique_test_id}",
            risk_score=68.0,
            risk_tier="high",
            risk_factors="{}",
            content_preview="Second pending item content",
            submitted_by="another_user",
            intake_path="mcp_ingest",
            submitted_at=datetime.utcnow(),
            status="pending_review",
        )

        with patch(
            "knowledge_base.governance.approval_engine.ApprovalEngine"
        ) as MockEngine:
            engine_instance = AsyncMock()
            engine_instance.get_pending_queue.return_value = [pending_1, pending_2]
            engine_instance.get_revertable_items.return_value = []
            engine_instance._ensure_table = AsyncMock()
            MockEngine.return_value = engine_instance

            await handle_governance_queue(ack, command, client)

        ack.assert_called_once()
        client.chat_postEphemeral.assert_called_once()
        call_kwargs = client.chat_postEphemeral.call_args

        # Check blocks contain pending items
        blocks = call_kwargs.kwargs.get("blocks", [])
        blocks_text = json.dumps(blocks)
        assert "Pending Approval" in blocks_text, (
            f"Should have 'Pending Approval' header. Blocks: {blocks_text[:300]}"
        )
        assert "2 items" in blocks_text, "Should show '2 items' count"

        # Verify approve/reject buttons for each item
        assert f"governance_approve_pending_1_{unique_test_id}" in blocks_text, (
            "Should have approve button for first item"
        )
        assert f"governance_reject_pending_1_{unique_test_id}" in blocks_text, (
            "Should have reject button for first item"
        )

    @pytest.mark.asyncio
    async def test_governance_queue_with_revertable_items(
        self,
        e2e_config,
        admin_channel_id,
        has_governance,
        unique_test_id,
    ):
        """Verify queue shows revertable items with Revert buttons."""
        from slack_sdk.web.async_client import AsyncWebClient

        from knowledge_base.slack.governance_admin import handle_governance_queue

        ack = AsyncMock()
        client = AsyncMock(spec=AsyncWebClient)

        command = {
            "user_id": "U_E2E_TEST",
            "channel_id": admin_channel_id,
        }

        revertable = KnowledgeGovernanceRecord(
            chunk_id=f"revert_{unique_test_id}",
            risk_score=45.0,
            risk_tier="medium",
            risk_factors="{}",
            content_preview="Revertable item content",
            submitted_by="test_user",
            intake_path="slack_create",
            submitted_at=datetime.utcnow(),
            status="auto_approved",
            revert_deadline=datetime.utcnow() + timedelta(hours=12),
        )

        with patch(
            "knowledge_base.governance.approval_engine.ApprovalEngine"
        ) as MockEngine:
            engine_instance = AsyncMock()
            engine_instance.get_pending_queue.return_value = []
            engine_instance.get_revertable_items.return_value = [revertable]
            engine_instance._ensure_table = AsyncMock()
            MockEngine.return_value = engine_instance

            await handle_governance_queue(ack, command, client)

        ack.assert_called_once()
        client.chat_postEphemeral.assert_called_once()
        call_kwargs = client.chat_postEphemeral.call_args

        blocks = call_kwargs.kwargs.get("blocks", [])
        blocks_text = json.dumps(blocks)
        assert "Revertable" in blocks_text, (
            f"Should have 'Revertable' header. Blocks: {blocks_text[:300]}"
        )
        assert f"governance_revert_revert_{unique_test_id}" in blocks_text, (
            "Should have revert button for the item"
        )


# =============================================================================
# Class 4: Create Knowledge with Governance
# =============================================================================


class TestGovernanceCreateKnowledge:
    """Test that /create-knowledge triggers governance classification.

    Slash commands can't be invoked via API, so we call the handler directly
    with mocked ack/command and a real AsyncWebClient.
    """

    @pytest.mark.asyncio
    async def test_create_knowledge_triggers_governance(
        self,
        e2e_config,
        admin_channel_id,
        has_governance,
        unique_test_id,
    ):
        """Verify /create-knowledge calls governance classification when enabled."""
        from slack_sdk.web.async_client import AsyncWebClient

        from knowledge_base.slack.quick_knowledge import handle_create_knowledge

        async_client = AsyncWebClient(token=e2e_config["bot_token"])
        ack = AsyncMock()

        command = {
            "text": f"E2E test governance classification {unique_test_id}",
            "user_id": "U_E2E_TEST",
            "user_name": "e2e_test_user",
            "channel_id": e2e_config["channel_id"],
        }

        # Mock GraphitiIndexer (top-level import in quick_knowledge.py -> patch where used)
        with patch(
            "knowledge_base.slack.quick_knowledge.GraphitiIndexer"
        ) as MockIndexer:
            mock_indexer = AsyncMock()
            MockIndexer.return_value = mock_indexer

            # Mock notify functions (lazy-imported in _process_with_governance,
            # but defined in governance_admin -> patch at source)
            with patch(
                "knowledge_base.slack.governance_admin.notify_admin_medium_risk",
                new_callable=AsyncMock,
            ) as mock_medium_notify:
                with patch(
                    "knowledge_base.slack.governance_admin.notify_admin_high_risk",
                    new_callable=AsyncMock,
                ) as mock_high_notify:
                    # Mock ApprovalEngine at source (lazy-imported in
                    # _process_with_governance)
                    with patch(
                        "knowledge_base.governance.approval_engine.ApprovalEngine"
                    ) as MockEngine:
                        from knowledge_base.governance.approval_engine import (
                            GovernanceResult,
                        )
                        from knowledge_base.governance.risk_classifier import (
                            RiskAssessment,
                        )

                        engine_instance = AsyncMock()
                        engine_instance.submit.return_value = GovernanceResult(
                            status="approved_with_revert",
                            risk_assessment=RiskAssessment(
                                score=31.75,
                                tier="medium",
                                factors={},
                                governance_status="approved",
                            ),
                            revert_deadline=datetime.utcnow() + timedelta(hours=24),
                            records=[MagicMock(chunk_id=f"test_{unique_test_id}")],
                        )
                        engine_instance._ensure_table = AsyncMock()
                        MockEngine.return_value = engine_instance

                        await handle_create_knowledge(ack, command, async_client)

                        # Allow background task to run
                        await asyncio.sleep(3)

        ack.assert_called_once()

        # Verify governance was triggered
        # With staging thresholds (LOW=25), a Slack user with @unknown domain
        # scores ~31.75 which is MEDIUM tier
        mock_indexer.index_single_chunk.assert_called_once()
        engine_instance.submit.assert_called_once()

        # Verify intake_path was set correctly
        submit_call = engine_instance.submit.call_args
        assert (
            submit_call.args[3] == "slack_create"
            or submit_call.kwargs.get("intake_path") == "slack_create"
            or "slack_create" in str(submit_call)
        ), f"intake_path should be 'slack_create'. Got: {submit_call}"

    @pytest.mark.asyncio
    async def test_create_knowledge_high_risk_notifies_admin(
        self,
        e2e_config,
        admin_channel_id,
        has_governance,
        unique_test_id,
    ):
        """Verify high-risk content triggers admin notification."""
        from slack_sdk.web.async_client import AsyncWebClient

        from knowledge_base.slack.quick_knowledge import handle_create_knowledge

        async_client = AsyncWebClient(token=e2e_config["bot_token"])
        ack = AsyncMock()

        command = {
            "text": f"E2E test high risk governance {unique_test_id}",
            "user_id": "U_E2E_TEST",
            "user_name": "e2e_test_user",
            "channel_id": e2e_config["channel_id"],
        }

        with patch(
            "knowledge_base.slack.quick_knowledge.GraphitiIndexer"
        ) as MockIndexer:
            mock_indexer = AsyncMock()
            MockIndexer.return_value = mock_indexer

            with patch(
                "knowledge_base.slack.governance_admin.notify_admin_medium_risk",
                new_callable=AsyncMock,
            ) as mock_medium_notify:
                with patch(
                    "knowledge_base.slack.governance_admin.notify_admin_high_risk",
                    new_callable=AsyncMock,
                ) as mock_high_notify:
                    with patch(
                        "knowledge_base.governance.approval_engine.ApprovalEngine"
                    ) as MockEngine:
                        from knowledge_base.governance.approval_engine import (
                            GovernanceResult,
                        )
                        from knowledge_base.governance.risk_classifier import (
                            RiskAssessment,
                        )

                        engine_instance = AsyncMock()
                        engine_instance.submit.return_value = GovernanceResult(
                            status="pending_review",
                            risk_assessment=RiskAssessment(
                                score=72.0,
                                tier="high",
                                factors={},
                                governance_status="pending",
                            ),
                            revert_deadline=None,
                            records=[
                                MagicMock(chunk_id=f"high_{unique_test_id}")
                            ],
                        )
                        engine_instance._ensure_table = AsyncMock()
                        MockEngine.return_value = engine_instance

                        await handle_create_knowledge(ack, command, async_client)

                        # Allow background task to run
                        await asyncio.sleep(3)

        ack.assert_called_once()
        mock_indexer.index_single_chunk.assert_called_once()
        engine_instance.submit.assert_called_once()

        # High-risk should trigger notify_admin_high_risk, not medium
        mock_high_notify.assert_called_once()
        mock_medium_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_knowledge_without_governance_skips_classification(
        self,
        e2e_config,
        unique_test_id,
    ):
        """Verify /create-knowledge skips governance when GOVERNANCE_ENABLED=False."""
        from slack_sdk.web.async_client import AsyncWebClient

        from knowledge_base.slack.quick_knowledge import handle_create_knowledge

        async_client = AsyncWebClient(token=e2e_config["bot_token"])
        ack = AsyncMock()

        command = {
            "text": f"E2E test no governance {unique_test_id}",
            "user_id": "U_E2E_TEST",
            "user_name": "e2e_test_user",
            "channel_id": e2e_config["channel_id"],
        }

        with patch(
            "knowledge_base.slack.quick_knowledge.settings"
        ) as mock_settings:
            mock_settings.GOVERNANCE_ENABLED = False

            with patch(
                "knowledge_base.slack.quick_knowledge.GraphitiIndexer"
            ) as MockIndexer:
                mock_indexer = AsyncMock()
                MockIndexer.return_value = mock_indexer

                with patch(
                    "knowledge_base.slack.quick_knowledge._process_with_governance",
                    new_callable=AsyncMock,
                ) as mock_governance:
                    await handle_create_knowledge(ack, command, async_client)

                    # Allow background task to run
                    await asyncio.sleep(3)

        ack.assert_called_once()

        # When governance is disabled, _process_with_governance should NOT be called
        mock_governance.assert_not_called()
        # Direct indexing should happen instead
        mock_indexer.index_single_chunk.assert_called_once()
