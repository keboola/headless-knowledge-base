"""Generate governance reports for content maintainers."""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from knowledge_base.db.models import (
    Chunk,
    ChunkQuality,
    DocumentationGap,
    GovernanceIssue,
    RawPage,
    UserFeedback,
)
from knowledge_base.governance.gap_analyzer import GapAnalyzer, GapInfo
from knowledge_base.governance.obsolete_detector import ObsoleteDetector, ObsoleteDocument

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class TopicCoverage:
    """Coverage statistics for a topic."""

    topic: str
    doc_count: int
    avg_quality: float
    query_count: int

    @property
    def coverage_ratio(self) -> float:
        if self.query_count == 0:
            return 1.0
        return self.doc_count / self.query_count


@dataclass
class SpaceStats:
    """Statistics for a Confluence space."""

    space_key: str
    total_pages: int
    active_pages: int
    obsolete_count: int
    avg_quality: float
    feedback_positive: int
    feedback_negative: int


@dataclass
class GovernanceReport:
    """Complete governance report."""

    generated_at: datetime
    period_days: int

    # Summary counts
    total_pages: int
    active_pages: int
    obsolete_count: int
    gap_count: int
    open_issues: int

    # Quality metrics
    avg_quality: float
    below_threshold_count: int

    # Feedback summary
    total_feedback: int
    positive_feedback: int
    negative_feedback: int

    # Details
    obsolete_docs: list[ObsoleteDocument] = field(default_factory=list)
    gaps: list[GapInfo] = field(default_factory=list)
    space_stats: list[SpaceStats] = field(default_factory=list)


class GovernanceReporter:
    """Generate comprehensive governance reports."""

    def __init__(
        self,
        session: Session,
        quality_threshold: float = 0.4,
    ):
        """Initialize governance reporter.

        Args:
            session: Database session
            quality_threshold: Threshold for flagging low quality
        """
        self.session = session
        self.quality_threshold = quality_threshold
        self.obsolete_detector = ObsoleteDetector(session)
        self.gap_analyzer = GapAnalyzer(session)

    def generate_report(self, days: int = 30) -> GovernanceReport:
        """Generate comprehensive governance report.

        Args:
            days: Period to analyze

        Returns:
            GovernanceReport with all metrics
        """
        logger.info(f"Generating governance report for last {days} days")

        # Get obsolete documents
        obsolete_docs = self.obsolete_detector.find_obsolete()

        # Get documentation gaps
        gaps = self.gap_analyzer.find_gaps(days=days)

        # Get page statistics
        page_stats = self._get_page_stats()

        # Get quality metrics
        quality_metrics = self._get_quality_metrics()

        # Get feedback summary
        feedback = self._get_feedback_summary(days)

        # Get open issues count
        open_issues = self._get_open_issues_count()

        # Get per-space stats
        space_stats = self._get_space_stats()

        report = GovernanceReport(
            generated_at=datetime.utcnow(),
            period_days=days,
            total_pages=page_stats["total"],
            active_pages=page_stats["active"],
            obsolete_count=len(obsolete_docs),
            gap_count=len(gaps),
            open_issues=open_issues,
            avg_quality=quality_metrics["avg"],
            below_threshold_count=quality_metrics["below_threshold"],
            total_feedback=feedback["total"],
            positive_feedback=feedback["positive"],
            negative_feedback=feedback["negative"],
            obsolete_docs=obsolete_docs,
            gaps=gaps,
            space_stats=space_stats,
        )

        logger.info(
            f"Report generated: {report.total_pages} pages, "
            f"{report.obsolete_count} obsolete, {report.gap_count} gaps"
        )

        return report

    def _get_page_stats(self) -> dict:
        """Get basic page statistics."""
        total = self.session.execute(
            select(func.count()).select_from(RawPage)
        ).scalar() or 0

        active = self.session.execute(
            select(func.count()).select_from(RawPage).where(RawPage.status == "active")
        ).scalar() or 0

        return {"total": total, "active": active}

    def _get_quality_metrics(self) -> dict:
        """Get quality score metrics."""
        avg_quality = self.session.execute(
            select(func.avg(ChunkQuality.quality_score))
        ).scalar() or 1.0

        below_threshold = self.session.execute(
            select(func.count()).select_from(ChunkQuality).where(
                ChunkQuality.quality_score < self.quality_threshold
            )
        ).scalar() or 0

        return {"avg": avg_quality, "below_threshold": below_threshold}

    def _get_feedback_summary(self, days: int) -> dict:
        """Get feedback summary for period."""
        since = datetime.utcnow() - timedelta(days=days)

        feedbacks = self.session.execute(
            select(UserFeedback).where(UserFeedback.created_at >= since)
        ).scalars().all()

        positive = sum(1 for f in feedbacks if f.feedback_type == "helpful")
        negative = sum(
            1 for f in feedbacks
            if f.feedback_type in ("outdated", "incorrect", "confusing")
        )

        return {
            "total": len(feedbacks),
            "positive": positive,
            "negative": negative,
        }

    def _get_open_issues_count(self) -> int:
        """Get count of open governance issues."""
        return self.session.execute(
            select(func.count()).select_from(GovernanceIssue).where(
                GovernanceIssue.status == "open"
            )
        ).scalar() or 0

    def _get_space_stats(self) -> list[SpaceStats]:
        """Get statistics per Confluence space."""
        # Get unique space keys
        spaces = self.session.execute(
            select(RawPage.space_key).distinct()
        ).scalars().all()

        stats = []
        for space_key in spaces:
            # Count pages
            total = self.session.execute(
                select(func.count()).select_from(RawPage).where(
                    RawPage.space_key == space_key
                )
            ).scalar() or 0

            active = self.session.execute(
                select(func.count()).select_from(RawPage).where(
                    RawPage.space_key == space_key,
                    RawPage.status == "active",
                )
            ).scalar() or 0

            # Get obsolete count for space
            obsolete = len(self.obsolete_detector.find_stale_by_space(space_key))

            # Get average quality (simplified)
            avg_quality = 1.0  # Default

            # Get feedback counts
            feedbacks = self.session.execute(
                select(UserFeedback).join(
                    Chunk, UserFeedback.chunk_id == Chunk.chunk_id
                ).join(
                    RawPage, Chunk.page_id == RawPage.page_id
                ).where(
                    RawPage.space_key == space_key
                )
            ).scalars().all()

            positive = sum(1 for f in feedbacks if f.feedback_type == "helpful")
            negative = sum(
                1 for f in feedbacks
                if f.feedback_type in ("outdated", "incorrect", "confusing")
            )

            stats.append(
                SpaceStats(
                    space_key=space_key,
                    total_pages=total,
                    active_pages=active,
                    obsolete_count=obsolete,
                    avg_quality=avg_quality,
                    feedback_positive=positive,
                    feedback_negative=negative,
                )
            )

        # Sort by total pages descending
        stats.sort(key=lambda s: s.total_pages, reverse=True)

        return stats

    def export_to_dict(self, report: GovernanceReport) -> dict:
        """Export report to dictionary for JSON serialization."""
        return {
            "generated_at": report.generated_at.isoformat(),
            "period_days": report.period_days,
            "summary": {
                "total_pages": report.total_pages,
                "active_pages": report.active_pages,
                "obsolete_count": report.obsolete_count,
                "gap_count": report.gap_count,
                "open_issues": report.open_issues,
            },
            "quality": {
                "average": report.avg_quality,
                "below_threshold": report.below_threshold_count,
            },
            "feedback": {
                "total": report.total_feedback,
                "positive": report.positive_feedback,
                "negative": report.negative_feedback,
            },
            "obsolete_docs": [
                {
                    "page_id": doc.page_id,
                    "title": doc.title,
                    "space_key": doc.space_key,
                    "reasons": doc.reasons,
                    "severity": doc.severity,
                }
                for doc in report.obsolete_docs
            ],
            "gaps": [
                {
                    "topic": gap.topic,
                    "query_count": gap.query_count,
                    "sample_queries": gap.sample_queries,
                    "suggested_title": gap.suggested_title,
                }
                for gap in report.gaps
            ],
            "space_stats": [
                {
                    "space_key": s.space_key,
                    "total_pages": s.total_pages,
                    "active_pages": s.active_pages,
                    "obsolete_count": s.obsolete_count,
                }
                for s in report.space_stats
            ],
        }
