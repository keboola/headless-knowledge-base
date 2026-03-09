"""Risk-based classifier for knowledge intake governance.

Scores incoming content on 4 weighted factors to determine the risk tier
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

# Content impact category to risk score mapping
_IMPACT_CATEGORY_SCORES: dict[str, float] = {
    "routine_info": 10.0,
    "team_update": 25.0,
    "process_change": 50.0,
    "tool_technology": 55.0,
    "org_structure": 75.0,
    "policy_change": 80.0,
    "financial_impact": 85.0,
    "security_change": 90.0,
}

_IMPACT_FALLBACK_SCORE: float = 20.0

_IMPACT_CLASSIFICATION_PROMPT = """Classify the organizational impact of this knowledge base content.

Categories (pick exactly one):
- routine_info: Casual facts, preferences, trivial updates with no organizational impact
- team_update: Changes affecting a single team's workflow or schedule
- process_change: Changes to how work gets done across multiple teams
- tool_technology: Technology, tool, or platform changes/decisions
- org_structure: Organizational structure, reporting, or team changes
- policy_change: Company-wide policies, rules, standards, mandates
- financial_impact: Budget, vendor, contract, procurement decisions
- security_change: Security policies, access controls, compliance requirements

Content: {content}

Return JSON: {{"category": "<category_name>", "confidence": <0.0-1.0>}}"""


class RiskClassifier:
    """Score intake requests on 4 weighted factors to determine risk tier.

    Factors:
        1. Author trust (15%): trusted domain -> low, unknown -> medium, external -> high
        2. Source type (15%): keboola_sync/batch -> low, create -> medium, ingest -> high
        3. Content scope (10%): short -> low risk, long -> higher risk
        4. Content impact (60%): LLM-classified organizational impact
    """

    async def classify(self, intake: IntakeRequest) -> RiskAssessment:
        """Score intake on 4 weighted factors.

        Returns:
            RiskAssessment with score, tier, factors dict, and governance_status
        """
        content_length = intake.content_length or len(intake.content)

        # Factor 1: Author trust (15%)
        author_trust = self._score_author_trust(intake.author_email)

        # Factor 2: Source type (15%)
        source_type = self._score_source_type(intake.intake_path)

        # Factor 3: Content scope (10%)
        content_scope = self._score_content_scope(content_length)

        # Factor 4: Content impact (60%) — LLM-based semantic classification
        content_impact, impact_category = await self._score_content_impact(
            intake.content
        )

        # Calculate weighted total score
        score = (
            author_trust * 0.15
            + source_type * 0.15
            + content_scope * 0.10
            + content_impact * 0.60
        )

        # Determine tier based on settings thresholds
        tier = self._determine_tier(score)
        governance_status = self._determine_governance_status(tier)

        factors = {
            "author_trust": author_trust,
            "source_type": source_type,
            "content_scope": content_scope,
            "content_impact": content_impact,
            "content_impact_category": impact_category,
        }

        logger.info(
            "Risk classification: score=%.1f, tier=%s, status=%s, "
            "path=%s, impact_category=%s",
            score, tier, governance_status, intake.intake_path, impact_category,
        )
        author_domain = intake.author_email.rsplit("@", 1)[-1] if "@" in intake.author_email else "unknown"
        logger.debug("Risk classification author domain: %s", author_domain)

        return RiskAssessment(
            score=score,
            tier=tier,
            factors=factors,
            governance_status=governance_status,
        )

    async def _score_content_impact(self, content: str) -> tuple[float, str]:
        """Score content impact using LLM classification.

        Uses Gemini to classify content into organizational impact categories.
        Falls back to default score on any LLM error.

        Returns:
            Tuple of (score 0-100, category name)
        """
        if not settings.GOVERNANCE_CONTENT_IMPACT_ENABLED:
            return _IMPACT_FALLBACK_SCORE, "disabled"

        try:
            from knowledge_base.rag.factory import get_llm

            llm = await get_llm()
            prompt = _IMPACT_CLASSIFICATION_PROMPT.format(
                content=content[:2000],  # Limit content length for prompt
            )
            result = await llm.generate_json(prompt)

            category = result.get("category", "").lower().strip()
            if category not in _IMPACT_CATEGORY_SCORES:
                logger.warning(
                    "LLM returned unknown impact category: %s, falling back",
                    category,
                )
                return _IMPACT_FALLBACK_SCORE, "unknown"

            score = _IMPACT_CATEGORY_SCORES[category]
            confidence = result.get("confidence", 0.0)
            logger.info(
                "Content impact classification: category=%s, score=%.0f, confidence=%.2f",
                category, score, confidence,
            )
            return score, category

        except Exception as e:
            logger.warning("Content impact classification failed, using fallback: %s", e)
            return _IMPACT_FALLBACK_SCORE, "error"

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
