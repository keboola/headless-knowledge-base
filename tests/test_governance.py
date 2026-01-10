"""Tests for the governance module."""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta

from knowledge_base.governance.obsolete_detector import (
    ObsoleteDetector,
    ObsoleteDocument,
    FeedbackStats,
)
from knowledge_base.governance.gap_analyzer import (
    GapAnalyzer,
    GapInfo,
    QueryCluster,
)
from knowledge_base.governance.reports import (
    GovernanceReporter,
    GovernanceReport,
    SpaceStats,
    TopicCoverage,
)


class TestFeedbackStats:
    """Tests for FeedbackStats dataclass."""

    def test_total_count(self):
        """Test total count calculation."""
        stats = FeedbackStats(positive_count=5, negative_count=3)
        assert stats.total == 8

    def test_negative_ratio(self):
        """Test negative ratio calculation."""
        stats = FeedbackStats(positive_count=5, negative_count=5)
        assert stats.negative_ratio == 0.5

    def test_negative_ratio_zero_total(self):
        """Test negative ratio with zero total."""
        stats = FeedbackStats(positive_count=0, negative_count=0)
        assert stats.negative_ratio == 0.0


class TestObsoleteDocument:
    """Tests for ObsoleteDocument dataclass."""

    def test_creation(self):
        """Test creating ObsoleteDocument."""
        doc = ObsoleteDocument(
            page_id="page123",
            title="Old Document",
            space_key="TEST",
            url="https://confluence/page123",
            last_updated=datetime.utcnow() - timedelta(days=800),
            quality_score=0.2,
            reasons=["Not updated in 800 days"],
            severity="high",
        )
        assert doc.page_id == "page123"
        assert doc.severity == "high"
        assert len(doc.reasons) == 1


class TestObsoleteDetector:
    """Tests for ObsoleteDetector."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.execute = MagicMock()
        session.add = MagicMock()
        session.commit = MagicMock()
        return session

    def test_init_defaults(self, mock_session):
        """Test default initialization."""
        detector = ObsoleteDetector(mock_session)
        assert detector.max_age_days == 730
        assert detector.min_quality == 0.3
        assert detector.max_negative_ratio == 0.5

    def test_init_custom(self, mock_session):
        """Test custom initialization."""
        detector = ObsoleteDetector(
            mock_session,
            max_age_days=365,
            min_quality=0.5,
            max_negative_ratio=0.3,
        )
        assert detector.max_age_days == 365
        assert detector.min_quality == 0.5

    def test_find_obsolete_no_pages(self, mock_session):
        """Test find_obsolete with no pages."""
        mock_session.execute.return_value.scalars.return_value.all.return_value = []
        detector = ObsoleteDetector(mock_session)
        result = detector.find_obsolete()
        assert result == []


class TestQueryCluster:
    """Tests for QueryCluster dataclass."""

    def test_size(self):
        """Test size property."""
        cluster = QueryCluster(
            queries=["q1", "q2", "q3"],
            representative_query="q1",
            avg_quality=0.3,
        )
        assert cluster.size == 3


class TestGapInfo:
    """Tests for GapInfo dataclass."""

    def test_creation(self):
        """Test creating GapInfo."""
        gap = GapInfo(
            topic="How to configure X",
            query_count=10,
            sample_queries=["q1", "q2"],
            suggested_title="Guide: How to configure X",
            avg_quality=0.25,
        )
        assert gap.topic == "How to configure X"
        assert gap.query_count == 10


class TestGapAnalyzer:
    """Tests for GapAnalyzer."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.execute = MagicMock()
        session.add = MagicMock()
        session.commit = MagicMock()
        return session

    def test_init_defaults(self, mock_session):
        """Test default initialization."""
        analyzer = GapAnalyzer(mock_session)
        assert analyzer.min_cluster_size == 3
        assert analyzer.similarity_threshold == 0.75
        assert analyzer.quality_threshold == 0.5

    def test_cluster_queries_simple(self, mock_session):
        """Test simple query clustering."""
        analyzer = GapAnalyzer(mock_session)
        queries = [
            ("how to configure VPN", 0.3),
            ("how to configure VPN access", 0.2),
            ("setup email", 0.4),
        ]

        clusters = analyzer._cluster_queries_simple(queries)
        assert len(clusters) >= 1

    def test_generate_title(self, mock_session):
        """Test title generation from cluster."""
        analyzer = GapAnalyzer(mock_session)
        cluster = QueryCluster(
            queries=["how to configure VPN?"],
            representative_query="how to configure VPN?",
        )

        title = analyzer._generate_title(cluster)
        assert title.startswith("Guide:")
        assert "VPN" in title

    def test_find_gaps_no_queries(self, mock_session):
        """Test find_gaps with no low-quality queries."""
        mock_session.execute.return_value.all.return_value = []
        analyzer = GapAnalyzer(mock_session)

        gaps = analyzer.find_gaps()
        assert gaps == []


class TestTopicCoverage:
    """Tests for TopicCoverage dataclass."""

    def test_coverage_ratio_with_queries(self):
        """Test coverage ratio calculation."""
        coverage = TopicCoverage(
            topic="onboarding",
            doc_count=5,
            avg_quality=0.8,
            query_count=10,
        )
        assert coverage.coverage_ratio == 0.5

    def test_coverage_ratio_no_queries(self):
        """Test coverage ratio with zero queries."""
        coverage = TopicCoverage(
            topic="onboarding",
            doc_count=5,
            avg_quality=0.8,
            query_count=0,
        )
        assert coverage.coverage_ratio == 1.0


class TestSpaceStats:
    """Tests for SpaceStats dataclass."""

    def test_creation(self):
        """Test creating SpaceStats."""
        stats = SpaceStats(
            space_key="ENG",
            total_pages=100,
            active_pages=90,
            obsolete_count=10,
            avg_quality=0.75,
            feedback_positive=50,
            feedback_negative=10,
        )
        assert stats.space_key == "ENG"
        assert stats.total_pages == 100


class TestGovernanceReporter:
    """Tests for GovernanceReporter."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.execute = MagicMock()
        return session

    def test_init_defaults(self, mock_session):
        """Test default initialization."""
        reporter = GovernanceReporter(mock_session)
        assert reporter.quality_threshold == 0.4

    def test_get_page_stats_empty(self, mock_session):
        """Test page stats with empty database."""
        mock_session.execute.return_value.scalar.return_value = 0
        reporter = GovernanceReporter(mock_session)

        stats = reporter._get_page_stats()
        assert stats["total"] == 0
        assert stats["active"] == 0

    def test_get_feedback_summary_empty(self, mock_session):
        """Test feedback summary with no feedback."""
        mock_session.execute.return_value.scalars.return_value.all.return_value = []
        reporter = GovernanceReporter(mock_session)

        summary = reporter._get_feedback_summary(30)
        assert summary["total"] == 0
        assert summary["positive"] == 0
        assert summary["negative"] == 0

    def test_export_to_dict(self, mock_session):
        """Test exporting report to dictionary."""
        reporter = GovernanceReporter(mock_session)

        report = GovernanceReport(
            generated_at=datetime.utcnow(),
            period_days=30,
            total_pages=100,
            active_pages=90,
            obsolete_count=5,
            gap_count=3,
            open_issues=2,
            avg_quality=0.75,
            below_threshold_count=10,
            total_feedback=50,
            positive_feedback=40,
            negative_feedback=10,
        )

        exported = reporter.export_to_dict(report)

        assert "generated_at" in exported
        assert exported["period_days"] == 30
        assert exported["summary"]["total_pages"] == 100
        assert exported["quality"]["average"] == 0.75
        assert exported["feedback"]["total"] == 50


class TestGovernanceReport:
    """Tests for GovernanceReport dataclass."""

    def test_creation(self):
        """Test creating GovernanceReport."""
        report = GovernanceReport(
            generated_at=datetime.utcnow(),
            period_days=30,
            total_pages=100,
            active_pages=90,
            obsolete_count=5,
            gap_count=3,
            open_issues=2,
            avg_quality=0.75,
            below_threshold_count=10,
            total_feedback=50,
            positive_feedback=40,
            negative_feedback=10,
        )

        assert report.total_pages == 100
        assert report.gap_count == 3
        assert len(report.obsolete_docs) == 0
        assert len(report.gaps) == 0
