"""Detect obsolete and stale content for governance review."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from knowledge_base.db.models import (
    ChunkQuality,
    GovernanceIssue,
    RawPage,
    UserFeedback,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Default thresholds
DEFAULT_MAX_AGE_DAYS = 730  # 2 years
DEFAULT_MIN_QUALITY = 0.3
DEFAULT_MAX_NEGATIVE_RATIO = 0.5


@dataclass
class ObsoleteDocument:
    """A document flagged as potentially obsolete."""

    page_id: str
    title: str
    space_key: str
    url: str
    last_updated: datetime
    quality_score: float
    reasons: list[str] = field(default_factory=list)
    severity: str = "medium"


@dataclass
class FeedbackStats:
    """Feedback statistics for a document."""

    positive_count: int = 0
    negative_count: int = 0

    @property
    def total(self) -> int:
        return self.positive_count + self.negative_count

    @property
    def negative_ratio(self) -> float:
        if self.total == 0:
            return 0.0
        return self.negative_count / self.total


class ObsoleteDetector:
    """Detect obsolete content based on age, quality, and feedback."""

    def __init__(
        self,
        session: Session,
        max_age_days: int = DEFAULT_MAX_AGE_DAYS,
        min_quality: float = DEFAULT_MIN_QUALITY,
        max_negative_ratio: float = DEFAULT_MAX_NEGATIVE_RATIO,
    ):
        """Initialize obsolete detector.

        Args:
            session: Database session
            max_age_days: Maximum age before flagging as stale
            min_quality: Minimum quality score
            max_negative_ratio: Maximum negative feedback ratio
        """
        self.session = session
        self.max_age_days = max_age_days
        self.min_quality = min_quality
        self.max_negative_ratio = max_negative_ratio

    def find_obsolete(self) -> list[ObsoleteDocument]:
        """Find documents that should be reviewed or removed.

        Returns:
            List of ObsoleteDocument entries
        """
        obsolete = []

        # Get all active pages
        pages = self.session.execute(
            select(RawPage).where(RawPage.status == "active")
        ).scalars().all()

        for page in pages:
            reasons = []
            severity = "low"

            # Check age
            age_days = (datetime.utcnow() - page.updated_at).days
            if age_days > self.max_age_days:
                reasons.append(f"Not updated in {age_days} days")
                if age_days > self.max_age_days * 2:
                    severity = "high"
                else:
                    severity = "medium"

            # Check quality score
            quality = self._get_quality_score(page.page_id)
            if quality < self.min_quality:
                reasons.append(f"Low quality score: {quality:.2f}")
                severity = "high" if quality < 0.2 else "medium"

            # Check negative feedback ratio
            feedback = self._get_feedback_stats(page.page_id)
            if feedback.total >= 5 and feedback.negative_ratio > self.max_negative_ratio:
                reasons.append(
                    f"High negative feedback: {feedback.negative_ratio:.0%} "
                    f"({feedback.negative_count}/{feedback.total})"
                )
                severity = "high"

            if reasons:
                obsolete.append(
                    ObsoleteDocument(
                        page_id=page.page_id,
                        title=page.title,
                        space_key=page.space_key,
                        url=page.url,
                        last_updated=page.updated_at,
                        quality_score=quality,
                        reasons=reasons,
                        severity=severity,
                    )
                )

        # Sort by severity (high first) then by age
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        obsolete.sort(
            key=lambda x: (severity_order.get(x.severity, 4), -len(x.reasons))
        )

        logger.info(f"Found {len(obsolete)} obsolete documents")
        return obsolete

    def _get_quality_score(self, page_id: str) -> float:
        """Get average quality score for page's chunks."""
        result = self.session.execute(
            select(func.avg(ChunkQuality.quality_score)).where(
                ChunkQuality.chunk_id.like(f"{page_id}%")
            )
        ).scalar()

        return result or 1.0  # Default to 1.0 if no scores

    def _get_feedback_stats(self, page_id: str) -> FeedbackStats:
        """Get feedback statistics for a page."""
        feedbacks = self.session.execute(
            select(UserFeedback).where(
                UserFeedback.chunk_id.like(f"{page_id}%")
            )
        ).scalars().all()

        positive = sum(1 for f in feedbacks if f.feedback_type == "helpful")
        negative = sum(
            1 for f in feedbacks
            if f.feedback_type in ("outdated", "incorrect", "confusing")
        )

        return FeedbackStats(positive_count=positive, negative_count=negative)

    def create_issues(self, obsolete_docs: list[ObsoleteDocument]) -> int:
        """Create governance issues for obsolete documents.

        Args:
            obsolete_docs: List of obsolete documents

        Returns:
            Number of issues created
        """
        created = 0

        for doc in obsolete_docs:
            # Check if issue already exists
            existing = self.session.execute(
                select(GovernanceIssue).where(
                    GovernanceIssue.page_id == doc.page_id,
                    GovernanceIssue.issue_type == "obsolete",
                    GovernanceIssue.status == "open",
                )
            ).scalar_one_or_none()

            if existing:
                continue

            issue = GovernanceIssue(
                page_id=doc.page_id,
                space_key=doc.space_key,
                issue_type="obsolete",
                description=f"Document '{doc.title}' flagged as obsolete: {'; '.join(doc.reasons)}",
                severity=doc.severity,
                detection_method="automatic",
            )

            self.session.add(issue)
            created += 1

        self.session.commit()
        logger.info(f"Created {created} governance issues for obsolete documents")

        return created

    def find_stale_by_space(self, space_key: str) -> list[ObsoleteDocument]:
        """Find obsolete documents in a specific space.

        Args:
            space_key: Confluence space key

        Returns:
            List of ObsoleteDocument entries for that space
        """
        all_obsolete = self.find_obsolete()
        return [doc for doc in all_obsolete if doc.space_key == space_key]
