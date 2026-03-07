"""Risk-based classifier for knowledge intake governance.

Scores incoming content on 5 weighted factors to determine the risk tier
(low / medium / high) and appropriate governance action.

See ADR-0011 for design rationale.
"""

import logging
from dataclasses import dataclass, field

from knowledge_base.config import settings

logger = logging.getLogger(__name__)


@dataclass
class IntakeRequest:
    """Describes a piece of content being submitted for intake."""

    author_email: str  # email or "username@unknown" for Slack
    intake_path: str  # slack_create, slack_ingest, mcp_create, mcp_ingest, keboola_sync, keboola_batch
    content: str
    chunk_count: int = 1
    content_length: int = 0  # auto-calculated from content if 0


@dataclass
class RiskAssessment:
    """Result of risk classification for an intake request."""

    score: float  # 0-100
    tier: str  # low / medium / high
    factors: dict[str, float] = field(default_factory=dict)  # individual factor scores
    governance_status: str = "approved"  # approved / pending


# Intake path to base risk score mapping
_SOURCE_SCORES: dict[str, float] = {
    "keboola_sync": 10,
    "keboola_batch": 10,
    "slack_create": 30,
    "mcp_create": 30,
    "slack_ingest": 70,
    "mcp_ingest": 70,
}


class RiskClassifier:
    """Score intake requests on 5 weighted factors to determine risk tier."""

    async def classify(self, intake: IntakeRequest) -> RiskAssessment:
        """Score intake on 5 weighted factors.

        Factors:
            1. Author trust (25%): trusted domain -> low, unknown -> medium, external -> high
            2. Source type (25%): keboola_sync/batch -> low, create -> medium, ingest -> high
            3. Content scope (15%): short -> low risk, long -> higher risk
            4. Novelty (20%): default 20 unless base risk >= 30 triggers deeper check
            5. Contradiction (15%): default 20 unless base risk >= 30 triggers deeper check

        Returns:
            RiskAssessment with score, tier, factors dict, and governance_status
        """
        content_length = intake.content_length or len(intake.content)

        # Factor 1: Author trust (25%)
        author_trust = self._score_author_trust(intake.author_email)

        # Factor 2: Source type (25%)
        source_type = self._score_source_type(intake.intake_path)

        # Factor 3: Content scope (15%)
        content_scope = self._score_content_scope(content_length)

        # Calculate base risk from factors 1-3 (weighted) to decide if expensive checks needed
        base_risk = (
            author_trust * 0.25
            + source_type * 0.25
            + content_scope * 0.15
        ) / 0.65  # Normalize to 0-100 scale for threshold comparison

        # Factor 4: Novelty (20%)
        if base_risk >= 30:
            # TODO: Wire embedding similarity check
            novelty = 20.0
        else:
            novelty = 20.0

        # Factor 5: Contradiction (15%)
        if base_risk >= 30:
            # TODO: Wire LLM contradiction check
            contradiction = 20.0
        else:
            contradiction = 20.0

        # Calculate weighted total score
        score = (
            author_trust * 0.25
            + source_type * 0.25
            + content_scope * 0.15
            + novelty * 0.20
            + contradiction * 0.15
        )

        # Determine tier based on settings thresholds
        tier = self._determine_tier(score)
        governance_status = self._determine_governance_status(tier)

        factors = {
            "author_trust": author_trust,
            "source_type": source_type,
            "content_scope": content_scope,
            "novelty": novelty,
            "contradiction": contradiction,
        }

        logger.info(
            f"Risk classification: score={score:.1f}, tier={tier}, "
            f"status={governance_status}, path={intake.intake_path}, "
            f"author={intake.author_email}"
        )

        return RiskAssessment(
            score=score,
            tier=tier,
            factors=factors,
            governance_status=governance_status,
        )

    def _score_author_trust(self, email: str) -> float:
        """Score author trust based on email domain.

        Returns:
            Score 0-100 (lower is more trusted)
        """
        if "@" not in email:
            return 80.0

        domain = email.rsplit("@", 1)[1].lower()

        if domain in [d.lower() for d in settings.governance_trusted_domain_list]:
            return 10.0
        if domain == "unknown":
            return 60.0
        return 80.0

    def _score_source_type(self, intake_path: str) -> float:
        """Score source type based on intake path.

        Returns:
            Score 0-100 (lower is more trusted)
        """
        return _SOURCE_SCORES.get(intake_path, 50.0)

    def _score_content_scope(self, content_length: int) -> float:
        """Score content scope based on content length.

        Longer content has higher potential impact and risk.

        Returns:
            Score 0-100
        """
        if content_length < 500:
            return 15.0
        if content_length < 2000:
            return 35.0
        if content_length < 5000:
            return 55.0
        return 75.0

    def _determine_tier(self, score: float) -> str:
        """Determine risk tier from score using settings thresholds."""
        if score <= settings.GOVERNANCE_LOW_RISK_THRESHOLD:
            return "low"
        if score >= settings.GOVERNANCE_HIGH_RISK_THRESHOLD:
            return "high"
        return "medium"

    def _determine_governance_status(self, tier: str) -> str:
        """Determine governance status from risk tier.

        - low: auto-approved
        - medium: approved with revert window
        - high: requires manual approval
        """
        if tier == "high":
            return "pending"
        return "approved"
