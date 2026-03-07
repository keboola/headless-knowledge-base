"""Tests for the KnowledgeGovernanceRecord SQLAlchemy model.

Uses an in-memory SQLite database to verify model creation, defaults,
constraints, and JSON round-trips.
"""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from knowledge_base.db.models import Base, KnowledgeGovernanceRecord


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_session():
    """Create an in-memory SQLite database with the governance table."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestKnowledgeGovernanceRecord:
    """Test the KnowledgeGovernanceRecord SQLAlchemy model."""

    def test_create_governance_record(self, db_session: Session) -> None:
        """Create and read back a governance record."""
        record = KnowledgeGovernanceRecord(
            chunk_id="chunk-001",
            risk_score=25.5,
            risk_tier="low",
            risk_factors='{"author_trust": 10.0, "source_type": 30.0}',
            intake_path="slack_create",
            submitted_by="alice@keboola.com",
            content_preview="Short knowledge fact.",
        )
        db_session.add(record)
        db_session.commit()

        fetched = db_session.query(KnowledgeGovernanceRecord).filter_by(
            chunk_id="chunk-001"
        ).one()

        assert fetched.chunk_id == "chunk-001"
        assert fetched.risk_score == 25.5
        assert fetched.risk_tier == "low"
        assert fetched.intake_path == "slack_create"
        assert fetched.submitted_by == "alice@keboola.com"
        assert fetched.content_preview == "Short knowledge fact."

    def test_status_default_is_pending_review(self, db_session: Session) -> None:
        """Verify default status is 'pending_review'."""
        record = KnowledgeGovernanceRecord(
            chunk_id="chunk-002",
            risk_score=50.0,
            risk_tier="medium",
            intake_path="mcp_create",
            submitted_by="bob@keboola.com",
        )
        db_session.add(record)
        db_session.commit()

        fetched = db_session.query(KnowledgeGovernanceRecord).filter_by(
            chunk_id="chunk-002"
        ).one()

        assert fetched.status == "pending_review"

    def test_risk_factors_json_roundtrip(self, db_session: Session) -> None:
        """Store JSON factors, read back, and verify as dict."""
        factors = {
            "author_trust": 10.0,
            "source_type": 30.0,
            "content_scope": 15.0,
            "novelty": 20.0,
            "contradiction": 20.0,
        }
        record = KnowledgeGovernanceRecord(
            chunk_id="chunk-003",
            risk_score=19.0,
            risk_tier="low",
            risk_factors=json.dumps(factors),
            intake_path="keboola_sync",
            submitted_by="system@keboola.com",
        )
        db_session.add(record)
        db_session.commit()

        fetched = db_session.query(KnowledgeGovernanceRecord).filter_by(
            chunk_id="chunk-003"
        ).one()

        loaded = json.loads(fetched.risk_factors)
        assert loaded == factors
        assert loaded["author_trust"] == 10.0

    def test_chunk_id_unique_constraint(self, db_session: Session) -> None:
        """Duplicate chunk_id raises IntegrityError."""
        record1 = KnowledgeGovernanceRecord(
            chunk_id="chunk-dup",
            risk_score=20.0,
            risk_tier="low",
            intake_path="slack_create",
            submitted_by="alice@keboola.com",
        )
        record2 = KnowledgeGovernanceRecord(
            chunk_id="chunk-dup",
            risk_score=40.0,
            risk_tier="medium",
            intake_path="mcp_ingest",
            submitted_by="bob@external.org",
        )
        db_session.add(record1)
        db_session.commit()

        db_session.add(record2)
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_nullable_review_fields(self, db_session: Session) -> None:
        """reviewed_by, reviewed_at, and review_note can be null."""
        record = KnowledgeGovernanceRecord(
            chunk_id="chunk-005",
            risk_score=30.0,
            risk_tier="low",
            intake_path="slack_create",
            submitted_by="alice@keboola.com",
        )
        db_session.add(record)
        db_session.commit()

        fetched = db_session.query(KnowledgeGovernanceRecord).filter_by(
            chunk_id="chunk-005"
        ).one()

        assert fetched.reviewed_by is None
        assert fetched.reviewed_at is None
        assert fetched.review_note is None
