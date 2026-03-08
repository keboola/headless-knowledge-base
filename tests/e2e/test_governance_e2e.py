"""E2E tests for knowledge governance feature.

Covers the full governance workflow:
- Admin notifications (high-risk / medium-risk) posted to Slack
- Button clicks for approve / reject / revert / mark-reviewed
- Governance-aware search filtering (pending, rejected, reverted excluded)
- create-knowledge with governance classification
- /governance-queue command handler

Prerequisites:
- E2E_ADMIN_CHANNEL set to admin channel ID
- SLACK_BOT_TOKEN / SLACK_USER_TOKEN
- Bot is a member of the admin channel
- SLACK_STAGING_SIGNING_SECRET for button click tests
"""

import json
import os
import types
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

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
def has_governance():
    """Skip if governance feature is disabled."""
    if not settings.GOVERNANCE_ENABLED:
        pytest.skip("GOVERNANCE_ENABLED is False")
    return True


@pytest.fixture
async def async_slack_client(e2e_config):
    """Provide an async Slack WebClient for calling governance_admin functions."""
    from slack_sdk.web.async_client import AsyncWebClient

    return AsyncWebClient(token=e2e_config["bot_token"])


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

    notify_admin_high_risk and notify_admin_medium_risk access:
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


def _mock_async_session_maker():
    """Return a pair of patches that replace async_session_maker in
    governance_admin and approval_engine with an in-memory SQLite session.

    Usage:
        with _mock_async_session_maker():
            await notify_admin_high_risk(...)
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    async def _init_tables():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    _session_factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def _session_ctx():
        async with _session_factory() as session:
            yield session

    class _PatchContext:
        """Combine two patches into a single context manager."""

        def __init__(self):
            self._patches = [
                patch(
                    "knowledge_base.slack.governance_admin.async_session_maker",
                    return_value=_session_ctx(),
                ),
                patch(
                    "knowledge_base.governance.approval_engine.async_session_maker",
                    return_value=_session_ctx(),
                ),
            ]
            self._mocks = []

        def __enter__(self):
            import asyncio
            # Run table init synchronously if loop is available
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # We are inside an async test -- schedule init via task
                    pass
            except RuntimeError:
                pass
            self._mocks = [p.start() for p in self._patches]
            return self

        def __exit__(self, *args):
            for p in self._patches:
                p.stop()

    return _PatchContext()


def _find_message_with_text(messages: list[dict], needle: str) -> dict | None:
    """Find a Slack message whose text or blocks contain *needle*."""
    for msg in messages:
        if needle in msg.get("text", ""):
            return msg
        for block in msg.get("blocks", []):
            if needle in json.dumps(block):
                return msg
    return None


# =============================================================================
# Class 1: Medium-Risk Notifications
# =============================================================================


class TestGovernanceMediumRiskNotification:
    """Verify medium-risk notifications appear in the admin channel."""

    @pytest.mark.asyncio
    async def test_medium_risk_posts_to_admin_channel(
        self,
        slack_client,
        e2e_config,
        admin_channel_id,
        async_slack_client,
        test_start_timestamp,
        unique_test_id,
    ):
        """notify_admin_medium_risk() posts Auto-Approved header with Revert + Mark Reviewed buttons."""
        import asyncio
        from knowledge_base.slack.governance_admin import notify_admin_medium_risk

        record = _make_governance_record(
            chunk_id=f"e2e_med_{unique_test_id}",
            risk_score=55.0,
            risk_tier="medium",
            status="auto_approved",
            content_preview=f"[E2E Test] Medium-risk content {unique_test_id}",
            revert_deadline=datetime.utcnow() + timedelta(hours=24),
        )

        with patch(
            "knowledge_base.slack.governance_admin._get_admin_channel",
            return_value=admin_channel_id,
        ):
            # Patch the DB write that updates slack_notification_ts
            with patch(
                "knowledge_base.slack.governance_admin.async_session_maker",
                new_callable=lambda: lambda: MagicMock(
                    __aenter__=AsyncMock(return_value=MagicMock(
                        execute=AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))),
                        commit=AsyncMock(),
                    )),
                    __aexit__=AsyncMock(return_value=False),
                ),
            ):
                ts = await notify_admin_medium_risk(async_slack_client, record)

        assert ts is not None, "notify_admin_medium_risk should return a ts"

        # Verify message is in admin channel
        await asyncio.sleep(2)

        history = slack_client.bot_client.conversations_history(
            channel=admin_channel_id,
            inclusive=True,
            oldest=ts,
            latest=ts,
            limit=1,
        )
        messages = history.get("messages", [])
        assert len(messages) > 0, "Notification not found in admin channel"

        msg = messages[0]

        # Check for Auto-Approved header
        blocks_str = json.dumps(msg.get("blocks", []))
        assert "Auto-Approved" in blocks_str, "Message should have Auto-Approved header"

        # Check for Revert and Mark Reviewed buttons
        assert slack_client.message_has_button(msg, "governance_revert"), (
            "Message should have Revert button"
        )
        assert slack_client.message_has_button(msg, "governance_mark_reviewed"), (
            "Message should have Mark Reviewed button"
        )

    @pytest.mark.asyncio
    async def test_mark_reviewed_button_click_succeeds(
        self,
        slack_client,
        e2e_config,
        admin_channel_id,
        async_slack_client,
        has_signing_secret,
        unique_test_id,
    ):
        """Click Mark Reviewed button on a medium-risk notification -- verify 200."""
        import asyncio
        from knowledge_base.slack.governance_admin import notify_admin_medium_risk

        record = _make_governance_record(
            chunk_id=f"e2e_mr_{unique_test_id}",
            risk_score=50.0,
            risk_tier="medium",
            status="auto_approved",
            content_preview=f"[E2E Test] Mark reviewed click {unique_test_id}",
            revert_deadline=datetime.utcnow() + timedelta(hours=24),
        )

        with patch(
            "knowledge_base.slack.governance_admin._get_admin_channel",
            return_value=admin_channel_id,
        ), patch(
            "knowledge_base.slack.governance_admin.async_session_maker",
            new_callable=lambda: lambda: MagicMock(
                __aenter__=AsyncMock(return_value=MagicMock(
                    execute=AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))),
                    commit=AsyncMock(),
                )),
                __aexit__=AsyncMock(return_value=False),
            ),
        ):
            ts = await notify_admin_medium_risk(async_slack_client, record)

        assert ts is not None

        await asyncio.sleep(2)

        # Fetch the posted message
        history = slack_client.bot_client.conversations_history(
            channel=admin_channel_id,
            inclusive=True,
            oldest=ts,
            latest=ts,
            limit=1,
        )
        messages = history.get("messages", [])
        assert len(messages) > 0
        msg = messages[0]

        # Click the Mark Reviewed button
        success = await slack_client.click_button(
            msg, "governance_mark_reviewed", channel_id=admin_channel_id,
        )
        assert success, "Mark Reviewed button click should return 200"

    @pytest.mark.asyncio
    async def test_revert_button_click_succeeds(
        self,
        slack_client,
        e2e_config,
        admin_channel_id,
        async_slack_client,
        has_signing_secret,
        unique_test_id,
    ):
        """Click Revert button on a medium-risk notification -- verify 200."""
        import asyncio
        from knowledge_base.slack.governance_admin import notify_admin_medium_risk

        record = _make_governance_record(
            chunk_id=f"e2e_rv_{unique_test_id}",
            risk_score=52.0,
            risk_tier="medium",
            status="auto_approved",
            content_preview=f"[E2E Test] Revert click {unique_test_id}",
            revert_deadline=datetime.utcnow() + timedelta(hours=24),
        )

        with patch(
            "knowledge_base.slack.governance_admin._get_admin_channel",
            return_value=admin_channel_id,
        ), patch(
            "knowledge_base.slack.governance_admin.async_session_maker",
            new_callable=lambda: lambda: MagicMock(
                __aenter__=AsyncMock(return_value=MagicMock(
                    execute=AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))),
                    commit=AsyncMock(),
                )),
                __aexit__=AsyncMock(return_value=False),
            ),
        ):
            ts = await notify_admin_medium_risk(async_slack_client, record)

        assert ts is not None

        await asyncio.sleep(2)

        history = slack_client.bot_client.conversations_history(
            channel=admin_channel_id,
            inclusive=True,
            oldest=ts,
            latest=ts,
            limit=1,
        )
        messages = history.get("messages", [])
        assert len(messages) > 0
        msg = messages[0]

        success = await slack_client.click_button(
            msg, "governance_revert", channel_id=admin_channel_id,
        )
        assert success, "Revert button click should return 200"


# =============================================================================
# Class 2: High-Risk Notifications
# =============================================================================


class TestGovernanceHighRiskNotification:
    """Verify high-risk notifications appear with Approve / Reject buttons."""

    @pytest.mark.asyncio
    async def test_high_risk_posts_to_admin_channel(
        self,
        slack_client,
        e2e_config,
        admin_channel_id,
        async_slack_client,
        test_start_timestamp,
        unique_test_id,
    ):
        """notify_admin_high_risk() posts Approval Request header with Approve + Reject buttons."""
        import asyncio
        from knowledge_base.slack.governance_admin import notify_admin_high_risk

        record = _make_governance_record(
            chunk_id=f"e2e_high_{unique_test_id}",
            risk_score=85.0,
            risk_tier="high",
            content_preview=f"[E2E Test] High-risk content {unique_test_id}",
        )

        with patch(
            "knowledge_base.slack.governance_admin._get_admin_channel",
            return_value=admin_channel_id,
        ), patch(
            "knowledge_base.slack.governance_admin.async_session_maker",
            new_callable=lambda: lambda: MagicMock(
                __aenter__=AsyncMock(return_value=MagicMock(
                    execute=AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))),
                    commit=AsyncMock(),
                )),
                __aexit__=AsyncMock(return_value=False),
            ),
        ):
            ts = await notify_admin_high_risk(async_slack_client, record)

        assert ts is not None, "notify_admin_high_risk should return a ts"

        await asyncio.sleep(2)

        history = slack_client.bot_client.conversations_history(
            channel=admin_channel_id,
            inclusive=True,
            oldest=ts,
            latest=ts,
            limit=1,
        )
        messages = history.get("messages", [])
        assert len(messages) > 0, "High-risk notification not found in admin channel"

        msg = messages[0]

        blocks_str = json.dumps(msg.get("blocks", []))
        assert "Approval Request" in blocks_str, "Message should have Approval Request header"

        assert slack_client.message_has_button(msg, "governance_approve"), (
            "Message should have Approve button"
        )
        assert slack_client.message_has_button(msg, "governance_reject"), (
            "Message should have Reject button"
        )

    @pytest.mark.asyncio
    async def test_approve_button_click_succeeds(
        self,
        slack_client,
        e2e_config,
        admin_channel_id,
        async_slack_client,
        has_signing_secret,
        unique_test_id,
    ):
        """Click Approve button on a high-risk notification -- verify 200."""
        import asyncio
        from knowledge_base.slack.governance_admin import notify_admin_high_risk

        record = _make_governance_record(
            chunk_id=f"e2e_apr_{unique_test_id}",
            risk_score=80.0,
            risk_tier="high",
            content_preview=f"[E2E Test] Approve click {unique_test_id}",
        )

        with patch(
            "knowledge_base.slack.governance_admin._get_admin_channel",
            return_value=admin_channel_id,
        ), patch(
            "knowledge_base.slack.governance_admin.async_session_maker",
            new_callable=lambda: lambda: MagicMock(
                __aenter__=AsyncMock(return_value=MagicMock(
                    execute=AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))),
                    commit=AsyncMock(),
                )),
                __aexit__=AsyncMock(return_value=False),
            ),
        ):
            ts = await notify_admin_high_risk(async_slack_client, record)

        assert ts is not None

        await asyncio.sleep(2)

        history = slack_client.bot_client.conversations_history(
            channel=admin_channel_id,
            inclusive=True,
            oldest=ts,
            latest=ts,
            limit=1,
        )
        messages = history.get("messages", [])
        assert len(messages) > 0
        msg = messages[0]

        success = await slack_client.click_button(
            msg, "governance_approve", channel_id=admin_channel_id,
        )
        assert success, "Approve button click should return 200"

    @pytest.mark.asyncio
    async def test_reject_button_click_opens_modal(
        self,
        slack_client,
        e2e_config,
        admin_channel_id,
        async_slack_client,
        has_signing_secret,
        unique_test_id,
    ):
        """Click Reject button on a high-risk notification -- verify 200 (modal opens)."""
        import asyncio
        from knowledge_base.slack.governance_admin import notify_admin_high_risk

        record = _make_governance_record(
            chunk_id=f"e2e_rej_{unique_test_id}",
            risk_score=82.0,
            risk_tier="high",
            content_preview=f"[E2E Test] Reject click {unique_test_id}",
        )

        with patch(
            "knowledge_base.slack.governance_admin._get_admin_channel",
            return_value=admin_channel_id,
        ), patch(
            "knowledge_base.slack.governance_admin.async_session_maker",
            new_callable=lambda: lambda: MagicMock(
                __aenter__=AsyncMock(return_value=MagicMock(
                    execute=AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))),
                    commit=AsyncMock(),
                )),
                __aexit__=AsyncMock(return_value=False),
            ),
        ):
            ts = await notify_admin_high_risk(async_slack_client, record)

        assert ts is not None

        await asyncio.sleep(2)

        history = slack_client.bot_client.conversations_history(
            channel=admin_channel_id,
            inclusive=True,
            oldest=ts,
            latest=ts,
            limit=1,
        )
        messages = history.get("messages", [])
        assert len(messages) > 0
        msg = messages[0]

        success = await slack_client.click_button(
            msg, "governance_reject", channel_id=admin_channel_id,
        )
        assert success, "Reject button click should return 200 (modal opens)"


# =============================================================================
# Class 3: Approve Updates Message
# =============================================================================


class TestGovernanceApproveUpdatesMessage:
    """Verify handle_governance_approve() updates the Slack message."""

    @pytest.mark.asyncio
    async def test_approve_updates_message_removes_buttons(
        self,
        slack_client,
        e2e_config,
        admin_channel_id,
        async_slack_client,
        unique_test_id,
    ):
        """Post high-risk notification then call handle_governance_approve() directly.

        Verify message is updated to say 'Approved' and buttons are removed.
        """
        import asyncio
        from knowledge_base.slack.governance_admin import (
            notify_admin_high_risk,
            handle_governance_approve,
        )

        chunk_id = f"e2e_apupd_{unique_test_id}"
        record = _make_governance_record(
            chunk_id=chunk_id,
            risk_score=78.0,
            risk_tier="high",
            content_preview=f"[E2E Test] Approve updates msg {unique_test_id}",
        )

        # Post the notification
        with patch(
            "knowledge_base.slack.governance_admin._get_admin_channel",
            return_value=admin_channel_id,
        ), patch(
            "knowledge_base.slack.governance_admin.async_session_maker",
            new_callable=lambda: lambda: MagicMock(
                __aenter__=AsyncMock(return_value=MagicMock(
                    execute=AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))),
                    commit=AsyncMock(),
                )),
                __aexit__=AsyncMock(return_value=False),
            ),
        ):
            ts = await notify_admin_high_risk(async_slack_client, record)

        assert ts is not None

        await asyncio.sleep(2)

        # Fetch the posted message to confirm it exists
        history = slack_client.bot_client.conversations_history(
            channel=admin_channel_id,
            inclusive=True,
            oldest=ts,
            latest=ts,
            limit=1,
        )
        messages = history.get("messages", [])
        assert len(messages) > 0

        # Now call handle_governance_approve directly
        ack_mock = AsyncMock()
        body = {
            "user": {"id": "U_E2E_ADMIN"},
            "channel": {"id": admin_channel_id},
            "message": {"ts": ts},
            "actions": [
                {"action_id": f"governance_approve_{chunk_id}"}
            ],
        }

        with patch(
            "knowledge_base.slack.governance_admin._is_admin_channel",
            return_value=True,
        ), patch(
            "knowledge_base.governance.approval_engine.ApprovalEngine.approve",
            new_callable=AsyncMock,
            return_value=True,
        ):
            await handle_governance_approve(ack_mock, body, async_slack_client)

        ack_mock.assert_called_once()

        # Poll for message update
        await asyncio.sleep(3)

        updated_history = slack_client.bot_client.conversations_history(
            channel=admin_channel_id,
            inclusive=True,
            oldest=ts,
            latest=ts,
            limit=1,
        )
        updated_messages = updated_history.get("messages", [])
        assert len(updated_messages) > 0

        updated_msg = updated_messages[0]
        blocks_str = json.dumps(updated_msg.get("blocks", []))
        text = updated_msg.get("text", "")

        # Verify "Approved" appears and buttons are gone
        assert "Approved" in blocks_str or "Approved" in text, (
            f"Message should contain 'Approved' after approval. "
            f"text={text!r}, blocks={blocks_str[:200]}"
        )

        has_approve_btn = slack_client.message_has_button(updated_msg, "governance_approve")
        has_reject_btn = slack_client.message_has_button(updated_msg, "governance_reject")
        assert not has_approve_btn, "Approve button should be removed after approval"
        assert not has_reject_btn, "Reject button should be removed after approval"


# =============================================================================
# Class 4: Search Filter
# =============================================================================


class TestGovernanceSearchFilter:
    """Verify governance-aware search filtering in GraphitiRetriever.

    Uses mocked graphiti.search() and _lookup_episodes() to test
    the filtering logic in search_chunks() without real Neo4j.
    """

    @staticmethod
    def _make_graphiti_result(
        *,
        name: str = "edge-1",
        fact: str | None = None,
        content: str | None = None,
        source_description: str | None = None,
        score: float = 0.9,
        episodes: list[str] | None = None,
    ) -> MagicMock:
        mock = MagicMock()
        mock.name = name
        mock.fact = fact
        mock.content = content
        mock.source_description = source_description
        mock.score = score
        mock.episodes = episodes or [str(uuid.uuid4())]
        mock.uuid = str(uuid.uuid4())
        return mock

    @staticmethod
    def _make_episode_data(
        *,
        name: str = "chunk-1",
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
        mock_settings: MagicMock,
        mock_get_client: MagicMock,
        *,
        governance_enabled: bool = True,
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
    async def test_pending_content_excluded(
        self, mock_settings: MagicMock, mock_get_client: MagicMock,
    ) -> None:
        """Episodes with governance_status='pending' are excluded when governance is enabled."""
        retriever, mock_graphiti = self._setup_retriever(
            mock_settings, mock_get_client, governance_enabled=True,
        )

        ep_uuid = str(uuid.uuid4())
        mock_graphiti.search = AsyncMock(
            return_value=[self._make_graphiti_result(name="edge-pending", score=0.9, episodes=[ep_uuid])]
        )

        with patch.object(retriever, "_lookup_episodes", new_callable=AsyncMock) as mock_lookup:
            mock_lookup.return_value = {
                ep_uuid: self._make_episode_data(
                    name="chunk-pending",
                    content="Pending content that should not appear in search results.",
                    metadata={"chunk_id": "chunk-pending", "governance_status": "pending"},
                ),
            }
            results = await retriever.search_chunks(query="test query", num_results=10)

        assert len(results) == 0, "Pending content should be excluded"

    @pytest.mark.asyncio
    @patch("knowledge_base.graph.graphiti_retriever.get_graphiti_client")
    @patch("knowledge_base.graph.graphiti_retriever.settings")
    async def test_rejected_content_excluded(
        self, mock_settings: MagicMock, mock_get_client: MagicMock,
    ) -> None:
        """Episodes with governance_status='rejected' are excluded when governance is enabled."""
        retriever, mock_graphiti = self._setup_retriever(
            mock_settings, mock_get_client, governance_enabled=True,
        )

        ep_uuid = str(uuid.uuid4())
        mock_graphiti.search = AsyncMock(
            return_value=[self._make_graphiti_result(name="edge-rejected", score=0.9, episodes=[ep_uuid])]
        )

        with patch.object(retriever, "_lookup_episodes", new_callable=AsyncMock) as mock_lookup:
            mock_lookup.return_value = {
                ep_uuid: self._make_episode_data(
                    name="chunk-rejected",
                    content="Rejected content that should not appear in search results.",
                    metadata={"chunk_id": "chunk-rejected", "governance_status": "rejected"},
                ),
            }
            results = await retriever.search_chunks(query="test query", num_results=10)

        assert len(results) == 0, "Rejected content should be excluded"

    @pytest.mark.asyncio
    @patch("knowledge_base.graph.graphiti_retriever.get_graphiti_client")
    @patch("knowledge_base.graph.graphiti_retriever.settings")
    async def test_reverted_content_excluded(
        self, mock_settings: MagicMock, mock_get_client: MagicMock,
    ) -> None:
        """CRITICAL: Episodes with governance_status='reverted' are excluded.

        This was previously missing from test coverage.
        """
        retriever, mock_graphiti = self._setup_retriever(
            mock_settings, mock_get_client, governance_enabled=True,
        )

        ep_uuid_good = str(uuid.uuid4())
        ep_uuid_reverted = str(uuid.uuid4())

        mock_graphiti.search = AsyncMock(return_value=[
            self._make_graphiti_result(name="edge-good", score=0.9, episodes=[ep_uuid_good]),
            self._make_graphiti_result(name="edge-reverted", score=0.8, episodes=[ep_uuid_reverted]),
        ])

        with patch.object(retriever, "_lookup_episodes", new_callable=AsyncMock) as mock_lookup:
            mock_lookup.return_value = {
                ep_uuid_good: self._make_episode_data(
                    name="chunk-good",
                    content="Approved content that should appear in search results.",
                    metadata={"chunk_id": "chunk-good", "governance_status": "approved"},
                ),
                ep_uuid_reverted: self._make_episode_data(
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
    async def test_approved_and_legacy_included(
        self, mock_settings: MagicMock, mock_get_client: MagicMock,
    ) -> None:
        """Episodes with 'approved' status and legacy episodes (missing field) are both included."""
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
    async def test_pending_to_approved_becomes_searchable(
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
# Class 5: Create Knowledge with Governance
# =============================================================================


class TestGovernanceCreateKnowledge:
    """Test _process_with_governance() in quick_knowledge.py."""

    @pytest.mark.asyncio
    async def test_create_knowledge_medium_risk_notifies_admin(
        self,
        slack_client,
        e2e_config,
        admin_channel_id,
        async_slack_client,
        unique_test_id,
    ):
        """Medium-risk content triggers notify_admin_medium_risk() and posts to admin channel."""
        import asyncio
        from knowledge_base.slack.quick_knowledge import _process_with_governance
        from knowledge_base.governance.risk_classifier import RiskAssessment
        from knowledge_base.governance.approval_engine import GovernanceResult
        from knowledge_base.vectorstore.indexer import ChunkData

        chunk_id = f"e2e_qk_med_{unique_test_id}"
        text = f"[E2E Test] Medium risk quick knowledge {unique_test_id}"

        chunk_data = ChunkData(
            chunk_id=chunk_id,
            content=text,
            page_id="quick_test",
            page_title="Quick Fact by e2e_user",
            chunk_index=0,
            space_key="QUICK",
            url="slack://user/U_TEST",
            author="unknown_user",
            created_at=datetime.utcnow().isoformat(),
            updated_at=datetime.utcnow().isoformat(),
            chunk_type="text",
            parent_headers="[]",
            quality_score=100.0,
            access_count=0,
            feedback_count=0,
            owner="unknown_user",
            reviewed_by="",
            reviewed_at="",
            classification="internal",
            doc_type="quick_fact",
            topics="[]",
            audience="[]",
            complexity="",
            summary=text[:200],
        )

        # Build a medium-risk assessment
        assessment = RiskAssessment(
            score=55.0,
            tier="medium",
            factors={"author_trust": 60, "source_type": 50},
            governance_status="approved",
        )

        # Build a governance result that signals approved_with_revert
        gov_record = _make_governance_record(
            chunk_id=chunk_id,
            risk_score=55.0,
            risk_tier="medium",
            status="auto_approved",
            content_preview=text[:300],
            revert_deadline=datetime.utcnow() + timedelta(hours=24),
        )
        gov_result = GovernanceResult(
            status="approved_with_revert",
            risk_assessment=assessment,
            revert_deadline=datetime.utcnow() + timedelta(hours=24),
            records=[gov_record],
        )

        # Track if notify_admin_medium_risk was called
        notify_called = []

        async def _mock_notify_medium(client, record):
            notify_called.append(record)
            # Actually post to admin channel for verification
            from knowledge_base.slack.governance_admin import notify_admin_medium_risk as _real
            with patch(
                "knowledge_base.slack.governance_admin._get_admin_channel",
                return_value=admin_channel_id,
            ), patch(
                "knowledge_base.slack.governance_admin.async_session_maker",
                new_callable=lambda: lambda: MagicMock(
                    __aenter__=AsyncMock(return_value=MagicMock(
                        execute=AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))),
                        commit=AsyncMock(),
                    )),
                    __aexit__=AsyncMock(return_value=False),
                ),
            ):
                return await _real(client, record)

        with patch(
            "knowledge_base.governance.risk_classifier.RiskClassifier"
        ) as MockClassifier, patch(
            "knowledge_base.governance.approval_engine.ApprovalEngine"
        ) as MockEngine, patch(
            "knowledge_base.graph.graphiti_indexer.GraphitiIndexer"
        ) as MockIndexer, patch(
            "knowledge_base.slack.governance_admin.notify_admin_medium_risk",
            side_effect=_mock_notify_medium,
        ), patch(
            "knowledge_base.slack.governance_admin.notify_admin_high_risk",
            new_callable=AsyncMock,
        ):
            classifier_instance = AsyncMock()
            classifier_instance.classify = AsyncMock(return_value=assessment)
            MockClassifier.return_value = classifier_instance

            engine_instance = AsyncMock()
            engine_instance.submit = AsyncMock(return_value=gov_result)
            MockEngine.return_value = engine_instance

            indexer_instance = AsyncMock()
            indexer_instance.index_single_chunk = AsyncMock()
            MockIndexer.return_value = indexer_instance

            await _process_with_governance(
                async_slack_client,
                chunk_data,
                text,
                "unknown_user",
                "U_TEST",
                e2e_config["channel_id"],
                chunk_id,
            )

        assert len(notify_called) == 1, "notify_admin_medium_risk should be called once"

        # Verify message appeared in admin channel
        await asyncio.sleep(3)

        history = slack_client.bot_client.conversations_history(
            channel=admin_channel_id,
            limit=10,
        )
        messages = history.get("messages", [])
        found = _find_message_with_text(messages, unique_test_id)
        assert found is not None, (
            f"Medium-risk notification should appear in admin channel. "
            f"Searched {len(messages)} recent messages for '{unique_test_id}'."
        )

    @pytest.mark.asyncio
    async def test_create_knowledge_low_risk_auto_approves(
        self,
        slack_client,
        e2e_config,
        admin_channel_id,
        async_slack_client,
        test_start_timestamp,
        unique_test_id,
    ):
        """Low-risk content auto-approves -- no admin notification, user gets 'Knowledge saved!'."""
        from knowledge_base.slack.quick_knowledge import _process_with_governance
        from knowledge_base.governance.risk_classifier import RiskAssessment
        from knowledge_base.governance.approval_engine import GovernanceResult

        chunk_id = f"e2e_qk_low_{unique_test_id}"
        text = f"[E2E Test] Low risk quick knowledge {unique_test_id}"

        # Minimal ChunkData
        from knowledge_base.vectorstore.indexer import ChunkData

        chunk_data = ChunkData(
            chunk_id=chunk_id,
            content=text,
            page_id="quick_test",
            page_title="Quick Fact by keboola_user",
            chunk_index=0,
            space_key="QUICK",
            url="slack://user/U_TEST",
            author="keboola_user@keboola.com",
            created_at=datetime.utcnow().isoformat(),
            updated_at=datetime.utcnow().isoformat(),
            chunk_type="text",
            parent_headers="[]",
            quality_score=100.0,
            access_count=0,
            feedback_count=0,
            owner="keboola_user",
            reviewed_by="",
            reviewed_at="",
            classification="internal",
            doc_type="quick_fact",
            topics="[]",
            audience="[]",
            complexity="",
            summary=text[:200],
        )

        assessment = RiskAssessment(
            score=15.0,
            tier="low",
            factors={"author_trust": 10, "source_type": 20},
            governance_status="approved",
        )

        gov_result = GovernanceResult(
            status="auto_approved",
            risk_assessment=assessment,
        )

        notify_high_mock = AsyncMock()
        notify_medium_mock = AsyncMock()

        with patch(
            "knowledge_base.governance.risk_classifier.RiskClassifier"
        ) as MockClassifier, patch(
            "knowledge_base.governance.approval_engine.ApprovalEngine"
        ) as MockEngine, patch(
            "knowledge_base.graph.graphiti_indexer.GraphitiIndexer"
        ) as MockIndexer, patch(
            "knowledge_base.slack.governance_admin.notify_admin_high_risk",
            notify_high_mock,
        ), patch(
            "knowledge_base.slack.governance_admin.notify_admin_medium_risk",
            notify_medium_mock,
        ):
            classifier_instance = AsyncMock()
            classifier_instance.classify = AsyncMock(return_value=assessment)
            MockClassifier.return_value = classifier_instance

            engine_instance = AsyncMock()
            engine_instance.submit = AsyncMock(return_value=gov_result)
            MockEngine.return_value = engine_instance

            indexer_instance = AsyncMock()
            indexer_instance.index_single_chunk = AsyncMock()
            MockIndexer.return_value = indexer_instance

            await _process_with_governance(
                async_slack_client,
                chunk_data,
                text,
                "keboola_user@keboola.com",
                "U_TEST",
                e2e_config["channel_id"],
                chunk_id,
            )

        # No admin notifications for low risk
        notify_high_mock.assert_not_called()
        notify_medium_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_governance_disabled_skips_classification(
        self,
        slack_client,
        e2e_config,
        async_slack_client,
        unique_test_id,
    ):
        """When GOVERNANCE_ENABLED=False, RiskClassifier is never called.

        Tests the branch in handle_create_knowledge() that skips governance.
        """
        from knowledge_base.slack.quick_knowledge import handle_create_knowledge

        ack_mock = AsyncMock()
        command = {
            "text": f"[E2E Test] No governance {unique_test_id}",
            "user_id": "U_TEST",
            "user_name": "test_user",
            "channel_id": e2e_config["channel_id"],
        }

        classifier_mock = MagicMock()

        with patch(
            "knowledge_base.slack.quick_knowledge.settings"
        ) as mock_settings, patch(
            "knowledge_base.graph.graphiti_indexer.GraphitiIndexer"
        ) as MockIndexer, patch(
            "knowledge_base.governance.risk_classifier.RiskClassifier",
            classifier_mock,
        ):
            mock_settings.GOVERNANCE_ENABLED = False
            mock_settings.SLACK_COMMAND_PREFIX = "kb-"

            indexer_instance = AsyncMock()
            indexer_instance.index_single_chunk = AsyncMock()
            MockIndexer.return_value = indexer_instance

            await handle_create_knowledge(ack_mock, command, async_slack_client)

            # Give the background task time to execute
            import asyncio
            await asyncio.sleep(2)

        ack_mock.assert_called_once()
        classifier_mock.assert_not_called()


# =============================================================================
# Class 6: Queue Handler
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
                risk_score=80.0,
                risk_tier="high",
                status="pending_review",
                content_preview="Pending item 1",
            ),
            _make_governance_record(
                chunk_id=f"pending_2_{unique_test_id}",
                risk_score=75.0,
                risk_tier="high",
                status="pending_review",
                content_preview="Pending item 2",
            ),
        ]

        revertable_items = [
            _make_governance_record(
                chunk_id=f"revertable_1_{unique_test_id}",
                risk_score=55.0,
                risk_tier="medium",
                status="auto_approved",
                content_preview="Revertable item 1",
                revert_deadline=datetime.utcnow() + timedelta(hours=12),
            ),
        ]

        ack_mock = AsyncMock()
        client_mock = AsyncMock()
        command = {
            "user_id": "U_TEST_ADMIN",
            "channel_id": "C_TEST_CHANNEL",
        }

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
        # Could be positional or keyword
        if call_kwargs.kwargs:
            blocks = call_kwargs.kwargs.get("blocks", [])
            text = call_kwargs.kwargs.get("text", "")
        else:
            blocks = []
            text = ""

        blocks_str = json.dumps(blocks)

        # Verify pending section header
        assert "Pending Approval" in blocks_str, (
            f"Queue should contain 'Pending Approval' header. blocks={blocks_str[:300]}"
        )

        # Verify revertable section header
        assert "Revertable" in blocks_str, (
            f"Queue should contain 'Revertable' header. blocks={blocks_str[:300]}"
        )

        # Verify chunk IDs appear
        assert f"pending_1_{unique_test_id}" in blocks_str
        assert f"pending_2_{unique_test_id}" in blocks_str
        assert f"revertable_1_{unique_test_id}" in blocks_str

    @pytest.mark.asyncio
    async def test_queue_empty(self, unique_test_id):
        """Empty queue shows 'No pending items' ephemeral."""
        from knowledge_base.slack.governance_admin import handle_governance_queue

        ack_mock = AsyncMock()
        client_mock = AsyncMock()
        command = {
            "user_id": "U_TEST_ADMIN",
            "channel_id": "C_TEST_CHANNEL",
        }

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
        if call_kwargs.kwargs:
            text = call_kwargs.kwargs.get("text", "")
        else:
            text = str(call_kwargs)

        assert "No pending items" in text, (
            f"Empty queue should say 'No pending items'. text={text!r}"
        )
