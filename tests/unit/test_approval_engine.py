"""Tests for the ApprovalEngine governance workflow.

Uses an async in-memory SQLite database to verify SQLite operations.
Neo4j interactions are mocked since unit tests cannot connect to real Neo4j.
"""

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from knowledge_base.db.models import Base, KnowledgeGovernanceRecord
from knowledge_base.governance.approval_engine import ApprovalEngine, GovernanceResult
from knowledge_base.governance.risk_classifier import RiskAssessment
from knowledge_base.vectorstore.indexer import ChunkData


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def assessment_low() -> RiskAssessment:
    """Low-risk assessment."""
    return RiskAssessment(
        score=20.0,
        tier="low",
        factors={"author_trust": 10.0, "source_type": 10.0},
        governance_status="approved",
    )


@pytest.fixture()
def assessment_medium() -> RiskAssessment:
    """Medium-risk assessment."""
    return RiskAssessment(
        score=50.0,
        tier="medium",
        factors={"author_trust": 60.0, "source_type": 30.0},
        governance_status="approved",
    )


@pytest.fixture()
def assessment_high() -> RiskAssessment:
    """High-risk assessment."""
    return RiskAssessment(
        score=75.0,
        tier="high",
        factors={"author_trust": 80.0, "source_type": 70.0},
        governance_status="pending",
    )


@pytest.fixture()
def sample_chunks() -> list[ChunkData]:
    """Sample chunks for testing."""
    return [
        ChunkData(
            chunk_id="chunk-001",
            content="This is some test content for chunk one.",
            page_id="page-1",
            page_title="Test Page",
            chunk_index=0,
        ),
        ChunkData(
            chunk_id="chunk-002",
            content="This is some test content for chunk two.",
            page_id="page-1",
            page_title="Test Page",
            chunk_index=1,
        ),
    ]


@pytest.fixture()
async def async_engine():
    """Create an async in-memory SQLite engine."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture()
async def session_maker(async_engine):
    """Create an async session maker bound to the in-memory engine."""
    return async_sessionmaker(
        async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


@pytest.fixture()
def engine_and_maker(async_engine, session_maker):
    """Patch async_session_maker to use our in-memory database."""
    with patch(
        "knowledge_base.governance.approval_engine.async_session_maker",
        session_maker,
    ):
        yield session_maker


@pytest.fixture()
def engine(engine_and_maker):
    """Return the patched session maker."""
    return engine_and_maker


@pytest.fixture()
def approval_engine(engine):
    """Create an ApprovalEngine with Neo4j updates mocked out."""
    ae = ApprovalEngine()
    with patch.object(ae, "_update_neo4j_governance_status", new_callable=AsyncMock):
        yield ae


# ---------------------------------------------------------------------------
# Submit tests
# ---------------------------------------------------------------------------


class TestSubmit:
    """Tests for ApprovalEngine.submit()."""

    @pytest.mark.asyncio
    async def test_submit_low_risk_auto_approves(
        self, approval_engine: ApprovalEngine, sample_chunks, assessment_low
    ) -> None:
        """Low tier -> status='auto_approved', no revert_deadline."""
        result = await approval_engine.submit(
            chunks=sample_chunks,
            assessment=assessment_low,
            submitted_by="alice@keboola.com",
            intake_path="keboola_sync",
        )

        assert result.status == "auto_approved"
        assert result.revert_deadline is None
        assert result.risk_assessment.tier == "low"

    @pytest.mark.asyncio
    async def test_submit_medium_risk_approves_with_revert(
        self, approval_engine: ApprovalEngine, sample_chunks, assessment_medium
    ) -> None:
        """Medium tier -> status='approved_with_revert', has revert_deadline."""
        result = await approval_engine.submit(
            chunks=sample_chunks,
            assessment=assessment_medium,
            submitted_by="alice@keboola.com",
            intake_path="slack_create",
        )

        assert result.status == "approved_with_revert"
        assert result.revert_deadline is not None
        # Deadline should be in the future (within expected window)
        assert result.revert_deadline > datetime.utcnow()

    @pytest.mark.asyncio
    async def test_submit_high_risk_sets_pending(
        self, approval_engine: ApprovalEngine, sample_chunks, assessment_high
    ) -> None:
        """High tier -> status='pending_review'."""
        result = await approval_engine.submit(
            chunks=sample_chunks,
            assessment=assessment_high,
            submitted_by="external@other.org",
            intake_path="mcp_ingest",
        )

        assert result.status == "pending_review"
        assert result.revert_deadline is None
        assert result.risk_assessment.tier == "high"

    @pytest.mark.asyncio
    async def test_submit_creates_sqlite_records(
        self,
        approval_engine: ApprovalEngine,
        engine,
        sample_chunks,
        assessment_low,
    ) -> None:
        """Records created in DB with correct fields."""
        await approval_engine.submit(
            chunks=sample_chunks,
            assessment=assessment_low,
            submitted_by="alice@keboola.com",
            intake_path="keboola_sync",
        )

        # Verify records in the database
        async with engine() as session:
            result = await session.execute(select(KnowledgeGovernanceRecord))
            records = list(result.scalars().all())

        assert len(records) == 2
        assert records[0].chunk_id == "chunk-001"
        assert records[1].chunk_id == "chunk-002"
        assert records[0].risk_score == 20.0
        assert records[0].risk_tier == "low"
        assert records[0].status == "auto_approved"
        assert records[0].submitted_by == "alice@keboola.com"
        assert records[0].intake_path == "keboola_sync"
        assert records[0].content_preview == "This is some test content for chunk one."

        # Verify risk_factors JSON
        factors = json.loads(records[0].risk_factors)
        assert factors["author_trust"] == 10.0


# ---------------------------------------------------------------------------
# Approve / Reject / Revert tests
# ---------------------------------------------------------------------------


class TestApprove:
    """Tests for ApprovalEngine.approve()."""

    @pytest.mark.asyncio
    async def test_approve_updates_status(
        self,
        approval_engine: ApprovalEngine,
        engine,
        sample_chunks,
        assessment_high,
    ) -> None:
        """pending -> approved, sets reviewed_by/at."""
        await approval_engine.submit(
            chunks=sample_chunks[:1],
            assessment=assessment_high,
            submitted_by="external@other.org",
            intake_path="mcp_ingest",
        )

        success = await approval_engine.approve(
            chunk_id="chunk-001",
            reviewed_by="admin@keboola.com",
            note="Looks good",
        )
        assert success is True

        # Verify in DB
        async with engine() as session:
            result = await session.execute(
                select(KnowledgeGovernanceRecord).where(
                    KnowledgeGovernanceRecord.chunk_id == "chunk-001"
                )
            )
            record = result.scalar_one()

        assert record.status == "approved"
        assert record.reviewed_by == "admin@keboola.com"
        assert record.reviewed_at is not None
        assert record.review_note == "Looks good"

    @pytest.mark.asyncio
    async def test_approve_nonexistent_returns_false(
        self, approval_engine: ApprovalEngine
    ) -> None:
        """chunk_id not found -> False."""
        success = await approval_engine.approve(
            chunk_id="nonexistent-chunk",
            reviewed_by="admin@keboola.com",
        )
        assert success is False

    @pytest.mark.asyncio
    async def test_approve_already_approved_returns_false(
        self,
        approval_engine: ApprovalEngine,
        sample_chunks,
        assessment_low,
    ) -> None:
        """Not pending (auto_approved) -> False."""
        await approval_engine.submit(
            chunks=sample_chunks[:1],
            assessment=assessment_low,
            submitted_by="alice@keboola.com",
            intake_path="keboola_sync",
        )

        # Try to approve an already auto_approved item
        success = await approval_engine.approve(
            chunk_id="chunk-001",
            reviewed_by="admin@keboola.com",
        )
        assert success is False


class TestReject:
    """Tests for ApprovalEngine.reject()."""

    @pytest.mark.asyncio
    async def test_reject_updates_status(
        self,
        approval_engine: ApprovalEngine,
        engine,
        sample_chunks,
        assessment_high,
    ) -> None:
        """pending -> rejected."""
        await approval_engine.submit(
            chunks=sample_chunks[:1],
            assessment=assessment_high,
            submitted_by="external@other.org",
            intake_path="mcp_ingest",
        )

        success = await approval_engine.reject(
            chunk_id="chunk-001",
            reviewed_by="admin@keboola.com",
            note="Not appropriate",
        )
        assert success is True

        # Verify in DB
        async with engine() as session:
            result = await session.execute(
                select(KnowledgeGovernanceRecord).where(
                    KnowledgeGovernanceRecord.chunk_id == "chunk-001"
                )
            )
            record = result.scalar_one()

        assert record.status == "rejected"
        assert record.reviewed_by == "admin@keboola.com"
        assert record.review_note == "Not appropriate"

    @pytest.mark.asyncio
    async def test_reject_nonexistent_returns_false(
        self, approval_engine: ApprovalEngine
    ) -> None:
        """chunk_id not found -> False."""
        success = await approval_engine.reject(
            chunk_id="nonexistent-chunk",
            reviewed_by="admin@keboola.com",
        )
        assert success is False


class TestRevert:
    """Tests for ApprovalEngine.revert()."""

    @pytest.mark.asyncio
    async def test_revert_within_window_succeeds(
        self,
        approval_engine: ApprovalEngine,
        engine,
        sample_chunks,
        assessment_medium,
    ) -> None:
        """revert_deadline in future -> True."""
        await approval_engine.submit(
            chunks=sample_chunks[:1],
            assessment=assessment_medium,
            submitted_by="alice@keboola.com",
            intake_path="slack_create",
        )

        success = await approval_engine.revert(
            chunk_id="chunk-001",
            reviewed_by="admin@keboola.com",
            note="Rolling back",
        )
        assert success is True

        # Verify in DB
        async with engine() as session:
            result = await session.execute(
                select(KnowledgeGovernanceRecord).where(
                    KnowledgeGovernanceRecord.chunk_id == "chunk-001"
                )
            )
            record = result.scalar_one()

        assert record.status == "reverted"
        assert record.reviewed_by == "admin@keboola.com"

    @pytest.mark.asyncio
    async def test_revert_after_window_fails(
        self,
        approval_engine: ApprovalEngine,
        engine,
        sample_chunks,
        assessment_medium,
    ) -> None:
        """revert_deadline in past -> False."""
        await approval_engine.submit(
            chunks=sample_chunks[:1],
            assessment=assessment_medium,
            submitted_by="alice@keboola.com",
            intake_path="slack_create",
        )

        # Manually set revert_deadline to the past
        async with engine() as session:
            result = await session.execute(
                select(KnowledgeGovernanceRecord).where(
                    KnowledgeGovernanceRecord.chunk_id == "chunk-001"
                )
            )
            record = result.scalar_one()
            record.revert_deadline = datetime.utcnow() - timedelta(hours=1)
            await session.commit()

        success = await approval_engine.revert(
            chunk_id="chunk-001",
            reviewed_by="admin@keboola.com",
        )
        assert success is False

    @pytest.mark.asyncio
    async def test_revert_nonexistent_returns_false(
        self, approval_engine: ApprovalEngine
    ) -> None:
        """chunk_id not found -> False."""
        success = await approval_engine.revert(
            chunk_id="nonexistent-chunk",
            reviewed_by="admin@keboola.com",
        )
        assert success is False

    @pytest.mark.asyncio
    async def test_revert_pending_item_returns_false(
        self,
        approval_engine: ApprovalEngine,
        sample_chunks,
        assessment_high,
    ) -> None:
        """Pending items (not auto_approved) cannot be reverted."""
        await approval_engine.submit(
            chunks=sample_chunks[:1],
            assessment=assessment_high,
            submitted_by="external@other.org",
            intake_path="mcp_ingest",
        )

        success = await approval_engine.revert(
            chunk_id="chunk-001",
            reviewed_by="admin@keboola.com",
        )
        assert success is False


# ---------------------------------------------------------------------------
# Query tests
# ---------------------------------------------------------------------------


class TestPendingQueue:
    """Tests for ApprovalEngine.get_pending_queue()."""

    @pytest.mark.asyncio
    async def test_get_pending_queue_returns_pending_only(
        self,
        approval_engine: ApprovalEngine,
        sample_chunks,
        assessment_low,
        assessment_high,
    ) -> None:
        """Mix of statuses, only pending returned."""
        # Submit low-risk (auto_approved) chunk
        low_chunk = ChunkData(
            chunk_id="low-001",
            content="Low risk content.",
            page_id="page-1",
            page_title="Test",
            chunk_index=0,
        )
        await approval_engine.submit(
            chunks=[low_chunk],
            assessment=assessment_low,
            submitted_by="alice@keboola.com",
            intake_path="keboola_sync",
        )

        # Submit high-risk (pending_review) chunk
        high_chunk = ChunkData(
            chunk_id="high-001",
            content="High risk content.",
            page_id="page-2",
            page_title="Risky Page",
            chunk_index=0,
        )
        await approval_engine.submit(
            chunks=[high_chunk],
            assessment=assessment_high,
            submitted_by="external@other.org",
            intake_path="mcp_ingest",
        )

        pending = await approval_engine.get_pending_queue()

        assert len(pending) == 1
        assert pending[0].chunk_id == "high-001"
        assert pending[0].status == "pending_review"

    @pytest.mark.asyncio
    async def test_get_pending_queue_empty_when_none_pending(
        self,
        approval_engine: ApprovalEngine,
        sample_chunks,
        assessment_low,
    ) -> None:
        """Empty list when no pending items."""
        await approval_engine.submit(
            chunks=sample_chunks[:1],
            assessment=assessment_low,
            submitted_by="alice@keboola.com",
            intake_path="keboola_sync",
        )

        pending = await approval_engine.get_pending_queue()
        assert len(pending) == 0


# ---------------------------------------------------------------------------
# Auto-reject tests
# ---------------------------------------------------------------------------


class TestAutoReject:
    """Tests for ApprovalEngine.auto_reject_expired()."""

    @pytest.mark.asyncio
    async def test_auto_reject_expired_items(
        self,
        approval_engine: ApprovalEngine,
        engine,
        assessment_high,
    ) -> None:
        """Old pending items get rejected."""
        # Submit a high-risk chunk
        chunk = ChunkData(
            chunk_id="old-001",
            content="Old pending content.",
            page_id="page-old",
            page_title="Old Page",
            chunk_index=0,
        )
        await approval_engine.submit(
            chunks=[chunk],
            assessment=assessment_high,
            submitted_by="external@other.org",
            intake_path="mcp_ingest",
        )

        # Manually set submitted_at to 15 days ago (beyond GOVERNANCE_AUTO_REJECT_DAYS=14)
        async with engine() as session:
            result = await session.execute(
                select(KnowledgeGovernanceRecord).where(
                    KnowledgeGovernanceRecord.chunk_id == "old-001"
                )
            )
            record = result.scalar_one()
            record.submitted_at = datetime.utcnow() - timedelta(days=15)
            await session.commit()

        count = await approval_engine.auto_reject_expired()
        assert count == 1

        # Verify status in DB
        async with engine() as session:
            result = await session.execute(
                select(KnowledgeGovernanceRecord).where(
                    KnowledgeGovernanceRecord.chunk_id == "old-001"
                )
            )
            record = result.scalar_one()

        assert record.status == "rejected"
        assert record.reviewed_by == "system"
        assert "Auto-rejected" in record.review_note

    @pytest.mark.asyncio
    async def test_auto_reject_skips_recent_items(
        self,
        approval_engine: ApprovalEngine,
        assessment_high,
    ) -> None:
        """Recent pending items are not auto-rejected."""
        chunk = ChunkData(
            chunk_id="recent-001",
            content="Recent pending content.",
            page_id="page-recent",
            page_title="Recent Page",
            chunk_index=0,
        )
        await approval_engine.submit(
            chunks=[chunk],
            assessment=assessment_high,
            submitted_by="external@other.org",
            intake_path="mcp_ingest",
        )

        count = await approval_engine.auto_reject_expired()
        assert count == 0


# ---------------------------------------------------------------------------
# Revertable items tests
# ---------------------------------------------------------------------------


class TestRevertableItems:
    """Tests for ApprovalEngine.get_revertable_items()."""

    @pytest.mark.asyncio
    async def test_get_revertable_items(
        self,
        approval_engine: ApprovalEngine,
        assessment_medium,
    ) -> None:
        """Medium-risk auto-approved items with future deadline are revertable."""
        chunk = ChunkData(
            chunk_id="med-001",
            content="Medium risk content.",
            page_id="page-med",
            page_title="Medium Page",
            chunk_index=0,
        )
        await approval_engine.submit(
            chunks=[chunk],
            assessment=assessment_medium,
            submitted_by="alice@keboola.com",
            intake_path="slack_create",
        )

        items = await approval_engine.get_revertable_items()
        assert len(items) == 1
        assert items[0].chunk_id == "med-001"

    @pytest.mark.asyncio
    async def test_get_revertable_items_excludes_expired(
        self,
        approval_engine: ApprovalEngine,
        engine,
        assessment_medium,
    ) -> None:
        """Items past their revert window are not returned."""
        chunk = ChunkData(
            chunk_id="expired-001",
            content="Expired revert window.",
            page_id="page-exp",
            page_title="Expired Page",
            chunk_index=0,
        )
        await approval_engine.submit(
            chunks=[chunk],
            assessment=assessment_medium,
            submitted_by="alice@keboola.com",
            intake_path="slack_create",
        )

        # Set revert_deadline to the past
        async with engine() as session:
            result = await session.execute(
                select(KnowledgeGovernanceRecord).where(
                    KnowledgeGovernanceRecord.chunk_id == "expired-001"
                )
            )
            record = result.scalar_one()
            record.revert_deadline = datetime.utcnow() - timedelta(hours=1)
            await session.commit()

        items = await approval_engine.get_revertable_items()
        assert len(items) == 0


# ---------------------------------------------------------------------------
# GovernanceResult dataclass tests
# ---------------------------------------------------------------------------


class TestGovernanceResult:
    """Tests for the GovernanceResult dataclass."""

    def test_governance_result_defaults(self) -> None:
        """Default values are correct."""
        result = GovernanceResult(
            status="auto_approved",
            risk_assessment=RiskAssessment(score=10.0, tier="low"),
        )
        assert result.revert_deadline is None
        assert result.records == []

    def test_governance_result_with_records(self) -> None:
        """Records field accepts a list."""
        record = KnowledgeGovernanceRecord(
            chunk_id="test-001",
            risk_score=10.0,
            risk_tier="low",
            intake_path="keboola_sync",
            submitted_by="alice@keboola.com",
        )
        result = GovernanceResult(
            status="auto_approved",
            risk_assessment=RiskAssessment(score=10.0, tier="low"),
            records=[record],
        )
        assert len(result.records) == 1
        assert result.records[0].chunk_id == "test-001"
