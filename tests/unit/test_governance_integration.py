"""Integration-style tests for governance wiring into intake paths.

Verifies that governance classification and approval are correctly invoked
from the Slack /create-knowledge, Slack /ingest-doc, and MCP create_knowledge
paths when GOVERNANCE_ENABLED=True, and bypassed when False.

All external systems (Graphiti, Neo4j, Slack) are mocked.
"""

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from knowledge_base.governance.approval_engine import GovernanceResult
from knowledge_base.governance.risk_classifier import RiskAssessment
from knowledge_base.vectorstore.indexer import ChunkData


# ---------------------------------------------------------------------------
# Shared helpers / fixtures
# ---------------------------------------------------------------------------

# Common patch targets for lazy imports in governance wiring
_CLASSIFIER_MODULE = "knowledge_base.governance.risk_classifier.RiskClassifier"
_ENGINE_MODULE = "knowledge_base.governance.approval_engine.ApprovalEngine"
_NOTIFY_HIGH = "knowledge_base.slack.governance_admin.notify_admin_high_risk"
_NOTIFY_MEDIUM = "knowledge_base.slack.governance_admin.notify_admin_medium_risk"


def _assessment(tier: str = "low", score: float = 20.0) -> RiskAssessment:
    """Build a RiskAssessment for testing."""
    governance_status = "pending" if tier == "high" else "approved"
    return RiskAssessment(
        score=score,
        tier=tier,
        factors={"author_trust": 10.0, "source_type": 30.0},
        governance_status=governance_status,
    )


def _governance_result(
    tier: str = "low",
    score: float = 20.0,
) -> GovernanceResult:
    """Build a GovernanceResult matching the tier."""
    assessment = _assessment(tier, score)
    status_map = {
        "low": "auto_approved",
        "medium": "approved_with_revert",
        "high": "pending_review",
    }
    revert_deadline = (
        datetime.utcnow() + timedelta(hours=24)
        if tier == "medium"
        else None
    )
    # Build a mock KnowledgeGovernanceRecord
    mock_record = MagicMock()
    mock_record.chunk_id = "test_chunk_0"
    mock_record.risk_score = score
    mock_record.risk_tier = tier
    mock_record.risk_factors = json.dumps(assessment.factors)
    mock_record.content_preview = "test content preview"
    mock_record.intake_path = "slack_create"
    mock_record.submitted_by = "testuser"
    mock_record.revert_deadline = revert_deadline

    return GovernanceResult(
        status=status_map[tier],
        risk_assessment=assessment,
        revert_deadline=revert_deadline,
        records=[mock_record],
    )


def _mock_client() -> MagicMock:
    """Return a mock Slack WebClient."""
    client = MagicMock()
    client.chat_postEphemeral = AsyncMock(return_value={"ok": True})
    client.chat_postMessage = AsyncMock(return_value={"ok": True, "ts": "1234.5678", "channel": "C123"})
    return client


# ---------------------------------------------------------------------------
# Slack /create-knowledge tests
# ---------------------------------------------------------------------------


class TestSlackCreateKnowledgeGovernance:
    """Test governance wiring in /create-knowledge handler."""

    @pytest.mark.asyncio
    @patch("knowledge_base.slack.quick_knowledge.settings")
    @patch("knowledge_base.slack.quick_knowledge.GraphitiIndexer")
    async def test_governance_disabled_passthrough(
        self, mock_indexer_cls, mock_settings,
    ) -> None:
        """When GOVERNANCE_ENABLED=False, classifier is NOT called and indexer runs normally."""
        mock_settings.GOVERNANCE_ENABLED = False
        mock_settings.SLACK_COMMAND_PREFIX = ""
        mock_indexer = AsyncMock()
        mock_indexer_cls.return_value = mock_indexer

        from knowledge_base.slack.quick_knowledge import handle_create_knowledge

        ack = AsyncMock()
        client = _mock_client()
        command = {
            "text": "Keboola uses Snowflake.",
            "user_id": "U123",
            "user_name": "alice",
            "channel_id": "C456",
        }

        await handle_create_knowledge(ack, command, client)
        # Wait for background task
        import asyncio
        await asyncio.sleep(0.1)

        # Indexer should have been called
        mock_indexer.index_single_chunk.assert_awaited_once()
        # User should get success message
        calls = client.chat_postEphemeral.call_args_list
        success_calls = [c for c in calls if "Knowledge saved" in str(c)]
        assert len(success_calls) >= 1

    @pytest.mark.asyncio
    async def test_governance_enabled_calls_classifier(self) -> None:
        """When GOVERNANCE_ENABLED=True, classifier and engine are called."""
        assessment = _assessment("low", 20.0)
        mock_classifier = AsyncMock()
        mock_classifier.classify.return_value = assessment

        mock_engine = AsyncMock()
        mock_engine.submit.return_value = _governance_result("low", 20.0)

        mock_indexer = AsyncMock()

        with (
            patch(_CLASSIFIER_MODULE, return_value=mock_classifier) as cls_patch,
            patch(_ENGINE_MODULE, return_value=mock_engine),
            patch("knowledge_base.slack.quick_knowledge.GraphitiIndexer", return_value=mock_indexer),
            patch("knowledge_base.slack.quick_knowledge.settings") as mock_settings,
        ):
            mock_settings.GOVERNANCE_ENABLED = True
            mock_settings.GOVERNANCE_REVERT_WINDOW_HOURS = 24

            from knowledge_base.slack.quick_knowledge import _process_with_governance

            client = _mock_client()
            chunk_data = ChunkData(
                chunk_id="quick_abc_0",
                content="Some fact",
                page_id="quick_abc",
                page_title="Quick Fact by alice",
                chunk_index=0,
            )

            await _process_with_governance(
                client, chunk_data, "Some fact", "alice", "U123", "C456", "quick_abc_0"
            )

        # Classifier should have been called
        mock_classifier.classify.assert_awaited_once()
        call_args = mock_classifier.classify.call_args[0][0]
        assert call_args.intake_path == "slack_create"
        assert call_args.author_email == "alice@unknown"

        # Chunk should have governance fields set
        assert chunk_data.governance_status == "approved"
        assert chunk_data.governance_risk_score == 20.0
        assert chunk_data.governance_risk_tier == "low"

        # Indexer should be called
        mock_indexer.index_single_chunk.assert_awaited_once_with(chunk_data)

        # Engine should record the decision
        mock_engine.submit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_high_risk_notifies_admin(self) -> None:
        """High-risk content sends admin notification and tells user it's under review."""
        assessment = _assessment("high", 75.0)
        mock_classifier = AsyncMock()
        mock_classifier.classify.return_value = assessment

        result = _governance_result("high", 75.0)
        mock_engine = AsyncMock()
        mock_engine.submit.return_value = result

        mock_indexer = AsyncMock()
        mock_notify_high = AsyncMock()

        with (
            patch(_CLASSIFIER_MODULE, return_value=mock_classifier),
            patch(_ENGINE_MODULE, return_value=mock_engine),
            patch("knowledge_base.slack.quick_knowledge.GraphitiIndexer", return_value=mock_indexer),
            patch(_NOTIFY_HIGH, mock_notify_high),
            patch("knowledge_base.slack.quick_knowledge.settings") as mock_settings,
        ):
            mock_settings.GOVERNANCE_ENABLED = True
            mock_settings.GOVERNANCE_REVERT_WINDOW_HOURS = 24

            from knowledge_base.slack.quick_knowledge import _process_with_governance

            client = _mock_client()
            chunk_data = ChunkData(
                chunk_id="quick_xyz_0",
                content="Some external content",
                page_id="quick_xyz",
                page_title="Quick Fact by bob",
                chunk_index=0,
            )

            await _process_with_governance(
                client, chunk_data, "Some external content", "bob", "U999", "C456", "quick_xyz_0"
            )

        # Admin notification should be sent
        mock_notify_high.assert_awaited_once()

        # User should get "submitted for review" message
        ephemeral_calls = client.chat_postEphemeral.call_args_list
        review_msgs = [c for c in ephemeral_calls if "submitted for admin review" in str(c)]
        assert len(review_msgs) >= 1

    @pytest.mark.asyncio
    async def test_low_risk_auto_approves(self) -> None:
        """Low-risk content auto-approves with standard success message."""
        mock_classifier = AsyncMock()
        mock_classifier.classify.return_value = _assessment("low", 20.0)

        mock_engine = AsyncMock()
        mock_engine.submit.return_value = _governance_result("low", 20.0)

        mock_indexer = AsyncMock()

        with (
            patch(_CLASSIFIER_MODULE, return_value=mock_classifier),
            patch(_ENGINE_MODULE, return_value=mock_engine),
            patch("knowledge_base.slack.quick_knowledge.GraphitiIndexer", return_value=mock_indexer),
            patch("knowledge_base.slack.quick_knowledge.settings") as mock_settings,
        ):
            mock_settings.GOVERNANCE_ENABLED = True
            mock_settings.GOVERNANCE_REVERT_WINDOW_HOURS = 24

            from knowledge_base.slack.quick_knowledge import _process_with_governance

            client = _mock_client()
            chunk_data = ChunkData(
                chunk_id="quick_low_0",
                content="Short fact",
                page_id="quick_low",
                page_title="Quick Fact by alice",
                chunk_index=0,
            )

            await _process_with_governance(
                client, chunk_data, "Short fact", "alice", "U123", "C456", "quick_low_0"
            )

        # User should get standard "Knowledge saved!" message
        ephemeral_calls = client.chat_postEphemeral.call_args_list
        success_msgs = [c for c in ephemeral_calls if "Knowledge saved!" in str(c)]
        assert len(success_msgs) >= 1

        # No admin review message
        review_msgs = [c for c in ephemeral_calls if "submitted for admin review" in str(c)]
        assert len(review_msgs) == 0

    @pytest.mark.asyncio
    async def test_medium_risk_approved_with_revert(self) -> None:
        """Medium-risk content is auto-approved with revert window."""
        mock_classifier = AsyncMock()
        mock_classifier.classify.return_value = _assessment("medium", 50.0)

        mock_engine = AsyncMock()
        mock_engine.submit.return_value = _governance_result("medium", 50.0)

        mock_indexer = AsyncMock()
        mock_notify_medium = AsyncMock()

        with (
            patch(_CLASSIFIER_MODULE, return_value=mock_classifier),
            patch(_ENGINE_MODULE, return_value=mock_engine),
            patch("knowledge_base.slack.quick_knowledge.GraphitiIndexer", return_value=mock_indexer),
            patch(_NOTIFY_MEDIUM, mock_notify_medium),
            patch("knowledge_base.slack.quick_knowledge.settings") as mock_settings,
        ):
            mock_settings.GOVERNANCE_ENABLED = True
            mock_settings.GOVERNANCE_REVERT_WINDOW_HOURS = 24

            from knowledge_base.slack.quick_knowledge import _process_with_governance

            client = _mock_client()
            chunk_data = ChunkData(
                chunk_id="quick_med_0",
                content="Medium risk content",
                page_id="quick_med",
                page_title="Quick Fact by user",
                chunk_index=0,
            )

            await _process_with_governance(
                client, chunk_data, "Medium risk content", "user", "U456", "C456", "quick_med_0"
            )

        # Admin notification for medium risk should be sent
        mock_notify_medium.assert_awaited_once()

        # User gets revert window message
        ephemeral_calls = client.chat_postEphemeral.call_args_list
        revert_msgs = [c for c in ephemeral_calls if "24h admin review" in str(c)]
        assert len(revert_msgs) >= 1


# ---------------------------------------------------------------------------
# MCP create_knowledge tests
# ---------------------------------------------------------------------------


class TestMCPCreateKnowledgeGovernance:
    """Test governance wiring in MCP create_knowledge tool.

    The MCP tools.py uses local imports inside _execute_create_knowledge,
    so we patch at the source modules (knowledge_base.config,
    knowledge_base.graph.graphiti_indexer) rather than knowledge_base.mcp.tools.
    """

    @pytest.mark.asyncio
    async def test_mcp_keboola_user_uses_email(self) -> None:
        """MCP with @keboola.com email passes it to IntakeRequest."""
        mock_classifier = AsyncMock()
        mock_classifier.classify.return_value = _assessment("low", 20.0)

        mock_engine = AsyncMock()
        mock_engine.submit.return_value = _governance_result("low", 20.0)

        mock_indexer = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.GOVERNANCE_ENABLED = True

        with (
            patch(_CLASSIFIER_MODULE, return_value=mock_classifier),
            patch(_ENGINE_MODULE, return_value=mock_engine),
            patch("knowledge_base.graph.graphiti_indexer.GraphitiIndexer", return_value=mock_indexer),
            patch("knowledge_base.config.settings", mock_settings),
        ):
            from knowledge_base.mcp.tools import _execute_create_knowledge

            result = await _execute_create_knowledge(
                {"content": "Test fact", "topics": []},
                {"email": "user@keboola.com", "sub": "user@keboola.com"},
            )

        # Verify classifier received the correct email
        call_args = mock_classifier.classify.call_args[0][0]
        assert call_args.author_email == "user@keboola.com"
        assert call_args.intake_path == "mcp_create"

    @pytest.mark.asyncio
    async def test_mcp_external_user(self) -> None:
        """MCP with external email passes it correctly."""
        mock_classifier = AsyncMock()
        mock_classifier.classify.return_value = _assessment("medium", 50.0)

        mock_engine = AsyncMock()
        mock_engine.submit.return_value = _governance_result("medium", 50.0)

        mock_indexer = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.GOVERNANCE_ENABLED = True

        with (
            patch(_CLASSIFIER_MODULE, return_value=mock_classifier),
            patch(_ENGINE_MODULE, return_value=mock_engine),
            patch("knowledge_base.graph.graphiti_indexer.GraphitiIndexer", return_value=mock_indexer),
            patch("knowledge_base.config.settings", mock_settings),
        ):
            from knowledge_base.mcp.tools import _execute_create_knowledge

            result = await _execute_create_knowledge(
                {"content": "External fact"},
                {"email": "user@external.com", "sub": "user@external.com"},
            )

        call_args = mock_classifier.classify.call_args[0][0]
        assert call_args.author_email == "user@external.com"

    @pytest.mark.asyncio
    async def test_mcp_governance_disabled(self) -> None:
        """When GOVERNANCE_ENABLED=False, indexer runs without governance."""
        mock_indexer = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.GOVERNANCE_ENABLED = False

        with (
            patch("knowledge_base.graph.graphiti_indexer.GraphitiIndexer", return_value=mock_indexer),
            patch("knowledge_base.config.settings", mock_settings),
        ):
            from knowledge_base.mcp.tools import _execute_create_knowledge

            result = await _execute_create_knowledge(
                {"content": "Simple fact"},
                {"email": "user@keboola.com"},
            )

        mock_indexer.index_single_chunk.assert_awaited_once()
        # Verify response doesn't contain governance info
        assert "Governance" not in result[0].text

    @pytest.mark.asyncio
    async def test_mcp_governance_info_in_response(self) -> None:
        """Governance info is included in MCP response when enabled."""
        mock_classifier = AsyncMock()
        mock_classifier.classify.return_value = _assessment("high", 75.0)

        mock_engine = AsyncMock()
        mock_engine.submit.return_value = _governance_result("high", 75.0)

        mock_indexer = AsyncMock()

        mock_settings = MagicMock()
        mock_settings.GOVERNANCE_ENABLED = True

        with (
            patch(_CLASSIFIER_MODULE, return_value=mock_classifier),
            patch(_ENGINE_MODULE, return_value=mock_engine),
            patch("knowledge_base.graph.graphiti_indexer.GraphitiIndexer", return_value=mock_indexer),
            patch("knowledge_base.config.settings", mock_settings),
        ):
            from knowledge_base.mcp.tools import _execute_create_knowledge

            result = await _execute_create_knowledge(
                {"content": "High risk content"},
                {"email": "external@unknown.com"},
            )

        # Response should include governance info
        assert "Governance" in result[0].text
        assert "pending_review" in result[0].text


# ---------------------------------------------------------------------------
# Ingest document governance tests
# ---------------------------------------------------------------------------


class TestIngestDocGovernance:
    """Test governance wiring in document ingestion."""

    @pytest.mark.asyncio
    async def test_governance_applies_to_all_chunks(self) -> None:
        """Governance fields should be set on ALL chunks during ingestion."""
        mock_classifier = AsyncMock()
        assessment = _assessment("medium", 50.0)
        mock_classifier.classify.return_value = assessment

        mock_engine = AsyncMock()
        mock_engine.submit.return_value = _governance_result("medium", 50.0)

        chunks = [
            ChunkData(
                chunk_id=f"ingest_test_{i}",
                content=f"Chunk content {i}",
                page_id="ingest_test",
                page_title="Test Document",
                chunk_index=i,
            )
            for i in range(5)
        ]

        with (
            patch(_CLASSIFIER_MODULE, return_value=mock_classifier),
            patch(_ENGINE_MODULE, return_value=mock_engine),
        ):
            from knowledge_base.slack.ingest_doc import DocumentIngester

            ingester = DocumentIngester()
            result = await ingester._apply_governance(
                chunks,
                "Full document content here",
                "testuser",
            )

        # All 5 chunks should have governance fields
        for chunk in chunks:
            assert chunk.governance_status == "approved"
            assert chunk.governance_risk_score == 50.0
            assert chunk.governance_risk_tier == "medium"

        # Engine.submit called with all 5 chunks
        mock_engine.submit.assert_awaited_once()
        submit_args = mock_engine.submit.call_args
        assert len(submit_args[0][0]) == 5
        assert submit_args[0][2] == "testuser"
        assert submit_args[0][3] == "slack_ingest"

    @pytest.mark.asyncio
    async def test_ingest_governance_disabled_passthrough(self) -> None:
        """When GOVERNANCE_ENABLED=False, chunks go straight to indexer."""
        mock_indexer = AsyncMock()
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        with (
            patch("knowledge_base.slack.ingest_doc.settings") as mock_settings,
            patch("knowledge_base.slack.ingest_doc.GraphitiIndexer", return_value=mock_indexer),
            patch("knowledge_base.slack.ingest_doc.async_session_maker", return_value=mock_session),
        ):
            mock_settings.GOVERNANCE_ENABLED = False

            from knowledge_base.slack.ingest_doc import DocumentIngester

            ingester = DocumentIngester()

            result = await ingester._create_and_index(
                url="https://example.com",
                title="Test Page",
                content="Some content to be chunked and indexed",
                created_by="testuser",
                source_type="webpage",
            )

        # Indexer should be called
        mock_indexer.index_chunks_direct.assert_awaited_once()
        # No governance fields in result
        assert "governance_status" not in result
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_ingest_email_detection(self) -> None:
        """Author email with @ is passed as-is; without @ gets @unknown suffix."""
        mock_classifier = AsyncMock()
        mock_classifier.classify.return_value = _assessment("low", 20.0)

        mock_engine = AsyncMock()
        mock_engine.submit.return_value = _governance_result("low", 20.0)

        chunk = ChunkData(
            chunk_id="test_0",
            content="Content",
            page_id="test",
            page_title="Test",
            chunk_index=0,
        )

        # Test with email
        with (
            patch(_CLASSIFIER_MODULE, return_value=mock_classifier),
            patch(_ENGINE_MODULE, return_value=mock_engine),
        ):
            from knowledge_base.slack.ingest_doc import DocumentIngester

            ingester = DocumentIngester()
            await ingester._apply_governance([chunk], "content", "user@keboola.com")

        call_args = mock_classifier.classify.call_args[0][0]
        assert call_args.author_email == "user@keboola.com"

        # Test without email (Slack user ID)
        mock_classifier.reset_mock()
        with (
            patch(_CLASSIFIER_MODULE, return_value=mock_classifier),
            patch(_ENGINE_MODULE, return_value=mock_engine),
        ):
            ingester = DocumentIngester()
            await ingester._apply_governance([chunk], "content", "U12345")

        call_args = mock_classifier.classify.call_args[0][0]
        assert call_args.author_email == "U12345@unknown"

    @pytest.mark.asyncio
    async def test_ingest_admin_notification_sent(self) -> None:
        """Admin notification is sent for high-risk ingestions when slack_client is provided."""
        mock_classifier = AsyncMock()
        mock_classifier.classify.return_value = _assessment("high", 75.0)

        mock_engine = AsyncMock()
        mock_engine.submit.return_value = _governance_result("high", 75.0)

        mock_notify = AsyncMock()

        chunk = ChunkData(
            chunk_id="test_0",
            content="Content",
            page_id="test",
            page_title="Test",
            chunk_index=0,
        )

        client = _mock_client()

        with (
            patch(_CLASSIFIER_MODULE, return_value=mock_classifier),
            patch(_ENGINE_MODULE, return_value=mock_engine),
            patch(_NOTIFY_HIGH, mock_notify),
        ):
            from knowledge_base.slack.ingest_doc import DocumentIngester

            ingester = DocumentIngester()
            await ingester._apply_governance(
                [chunk], "content", "external_user", slack_client=client,
            )

        mock_notify.assert_awaited_once()


# ---------------------------------------------------------------------------
# ChunkData governance metadata propagation
# ---------------------------------------------------------------------------


class TestChunkDataGovernanceMetadata:
    """Test that governance fields propagate to Neo4j metadata."""

    def test_governance_fields_in_to_metadata(self) -> None:
        """to_metadata() should include governance_status, risk_score, risk_tier."""
        chunk = ChunkData(
            chunk_id="test_0",
            content="Some content",
            page_id="test",
            page_title="Test",
            chunk_index=0,
            governance_status="pending",
            governance_risk_score=75.0,
            governance_risk_tier="high",
        )
        metadata = chunk.to_metadata()

        assert metadata["governance_status"] == "pending"
        assert metadata["governance_risk_score"] == 75.0
        assert metadata["governance_risk_tier"] == "high"

    def test_governance_defaults_in_to_metadata(self) -> None:
        """Default governance values should be present in metadata."""
        chunk = ChunkData(
            chunk_id="test_0",
            content="Content",
            page_id="test",
            page_title="Test",
            chunk_index=0,
        )
        metadata = chunk.to_metadata()

        assert metadata["governance_status"] == "approved"
        assert metadata["governance_risk_score"] == 0.0
        assert metadata["governance_risk_tier"] == "low"
