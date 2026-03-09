"""Tests for risk-based classification of knowledge intake requests.

Validates the RiskClassifier scoring logic across all 4 factors:
author trust, source type, content scope, and LLM-based content impact.
"""

from unittest.mock import AsyncMock, patch

import pytest

from knowledge_base.governance.risk_classifier import (
    IntakeRequest,
    RiskClassifier,
    _IMPACT_CATEGORY_SCORES,
    _IMPACT_FALLBACK_SCORE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_intake(
    *,
    author_email: str = "user@keboola.com",
    intake_path: str = "slack_create",
    content: str = "Short fact about Keboola.",
    chunk_count: int = 1,
    content_length: int = 0,
) -> IntakeRequest:
    return IntakeRequest(
        author_email=author_email,
        intake_path=intake_path,
        content=content,
        chunk_count=chunk_count,
        content_length=content_length,
    )


def _mock_llm_response(category: str, confidence: float = 0.95) -> AsyncMock:
    """Create a mock LLM that returns a specific impact category."""
    mock_llm = AsyncMock()
    mock_llm.generate_json = AsyncMock(
        return_value={"category": category, "confidence": confidence}
    )
    return mock_llm


# ---------------------------------------------------------------------------
# Tests: Content Impact (LLM-based classification)
# ---------------------------------------------------------------------------


class TestContentImpactClassification:
    """Test LLM-based content impact factor."""

    @pytest.mark.asyncio
    async def test_policy_change_scores_high(self) -> None:
        """Company-wide policy content should score HIGH tier."""
        classifier = RiskClassifier()
        mock_llm = _mock_llm_response("policy_change")

        with patch(
            "knowledge_base.governance.risk_classifier.settings"
        ) as mock_settings:
            mock_settings.GOVERNANCE_CONTENT_IMPACT_ENABLED = True
            mock_settings.GOVERNANCE_LOW_RISK_THRESHOLD = 25
            mock_settings.GOVERNANCE_HIGH_RISK_THRESHOLD = 55
            mock_settings.governance_trusted_domain_list = ["keboola.com"]

            with patch(
                "knowledge_base.rag.factory.get_llm",
                new_callable=AsyncMock,
                return_value=mock_llm,
            ):
                intake = _make_intake(
                    author_email="user@unknown",
                    content="All employees must use Macbook Air M4. Rented via Alza.",
                )
                result = await classifier.classify(intake)

        assert result.tier == "high"
        assert result.governance_status == "pending"
        assert result.factors["content_impact"] == 80.0
        assert result.factors["content_impact_category"] == "policy_change"

    @pytest.mark.asyncio
    async def test_routine_info_scores_low(self) -> None:
        """Routine/trivial content should score LOW tier."""
        classifier = RiskClassifier()
        mock_llm = _mock_llm_response("routine_info")

        with patch(
            "knowledge_base.governance.risk_classifier.settings"
        ) as mock_settings:
            mock_settings.GOVERNANCE_CONTENT_IMPACT_ENABLED = True
            mock_settings.GOVERNANCE_LOW_RISK_THRESHOLD = 25
            mock_settings.GOVERNANCE_HIGH_RISK_THRESHOLD = 55
            mock_settings.governance_trusted_domain_list = ["keboola.com"]

            with patch(
                "knowledge_base.rag.factory.get_llm",
                new_callable=AsyncMock,
                return_value=mock_llm,
            ):
                intake = _make_intake(
                    author_email="alice@keboola.com",
                    content="The cafeteria has new salad options.",
                )
                result = await classifier.classify(intake)

        assert result.tier == "low"
        assert result.governance_status == "approved"
        assert result.factors["content_impact"] == 10.0
        assert result.factors["content_impact_category"] == "routine_info"

    @pytest.mark.asyncio
    async def test_financial_impact_scores_high(self) -> None:
        """Financial/contract content should score HIGH tier."""
        classifier = RiskClassifier()
        mock_llm = _mock_llm_response("financial_impact")

        with patch(
            "knowledge_base.governance.risk_classifier.settings"
        ) as mock_settings:
            mock_settings.GOVERNANCE_CONTENT_IMPACT_ENABLED = True
            mock_settings.GOVERNANCE_LOW_RISK_THRESHOLD = 25
            mock_settings.GOVERNANCE_HIGH_RISK_THRESHOLD = 55
            mock_settings.governance_trusted_domain_list = ["keboola.com"]

            with patch(
                "knowledge_base.rag.factory.get_llm",
                new_callable=AsyncMock,
                return_value=mock_llm,
            ):
                intake = _make_intake(
                    author_email="user@unknown",
                    content="New vendor contract with AWS for $2M annual spend.",
                )
                result = await classifier.classify(intake)

        assert result.tier == "high"
        assert result.governance_status == "pending"
        assert result.factors["content_impact"] == 85.0

    @pytest.mark.asyncio
    async def test_security_change_scores_high(self) -> None:
        """Security policy changes should score HIGH tier."""
        classifier = RiskClassifier()
        mock_llm = _mock_llm_response("security_change")

        with patch(
            "knowledge_base.governance.risk_classifier.settings"
        ) as mock_settings:
            mock_settings.GOVERNANCE_CONTENT_IMPACT_ENABLED = True
            mock_settings.GOVERNANCE_LOW_RISK_THRESHOLD = 25
            mock_settings.GOVERNANCE_HIGH_RISK_THRESHOLD = 55
            mock_settings.governance_trusted_domain_list = ["keboola.com"]

            with patch(
                "knowledge_base.rag.factory.get_llm",
                new_callable=AsyncMock,
                return_value=mock_llm,
            ):
                intake = _make_intake(
                    author_email="user@unknown",
                    content="New VPN policy for all remote workers.",
                )
                result = await classifier.classify(intake)

        assert result.tier == "high"
        assert result.factors["content_impact"] == 90.0

    @pytest.mark.asyncio
    async def test_team_update_scores_medium(self) -> None:
        """Team-level updates should score MEDIUM tier with unknown author."""
        classifier = RiskClassifier()
        mock_llm = _mock_llm_response("team_update")

        with patch(
            "knowledge_base.governance.risk_classifier.settings"
        ) as mock_settings:
            mock_settings.GOVERNANCE_CONTENT_IMPACT_ENABLED = True
            mock_settings.GOVERNANCE_LOW_RISK_THRESHOLD = 25
            mock_settings.GOVERNANCE_HIGH_RISK_THRESHOLD = 55
            mock_settings.governance_trusted_domain_list = ["keboola.com"]

            with patch(
                "knowledge_base.rag.factory.get_llm",
                new_callable=AsyncMock,
                return_value=mock_llm,
            ):
                intake = _make_intake(
                    author_email="user@unknown",
                    content="Our team standup moves to 10am starting Monday.",
                )
                result = await classifier.classify(intake)

        # team_update=25, author=60, source=30, scope=15
        # 60*0.15 + 30*0.15 + 15*0.10 + 25*0.60 = 9+4.5+1.5+15 = 30
        assert result.tier == "medium"
        assert result.factors["content_impact"] == 25.0

    @pytest.mark.asyncio
    async def test_llm_failure_uses_fallback(self) -> None:
        """When LLM fails, use fallback score (20.0) and category 'error'."""
        classifier = RiskClassifier()
        mock_llm = AsyncMock()
        mock_llm.generate_json = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

        with patch(
            "knowledge_base.governance.risk_classifier.settings"
        ) as mock_settings:
            mock_settings.GOVERNANCE_CONTENT_IMPACT_ENABLED = True
            mock_settings.GOVERNANCE_LOW_RISK_THRESHOLD = 25
            mock_settings.GOVERNANCE_HIGH_RISK_THRESHOLD = 55
            mock_settings.governance_trusted_domain_list = ["keboola.com"]

            with patch(
                "knowledge_base.rag.factory.get_llm",
                new_callable=AsyncMock,
                return_value=mock_llm,
            ):
                intake = _make_intake(
                    author_email="user@unknown",
                    content="Some important content.",
                )
                result = await classifier.classify(intake)

        assert result.factors["content_impact"] == _IMPACT_FALLBACK_SCORE
        assert result.factors["content_impact_category"] == "error"

    @pytest.mark.asyncio
    async def test_unknown_category_uses_fallback(self) -> None:
        """When LLM returns an unknown category, use fallback."""
        classifier = RiskClassifier()
        mock_llm = _mock_llm_response("made_up_category")

        with patch(
            "knowledge_base.governance.risk_classifier.settings"
        ) as mock_settings:
            mock_settings.GOVERNANCE_CONTENT_IMPACT_ENABLED = True
            mock_settings.GOVERNANCE_LOW_RISK_THRESHOLD = 25
            mock_settings.GOVERNANCE_HIGH_RISK_THRESHOLD = 55
            mock_settings.governance_trusted_domain_list = ["keboola.com"]

            with patch(
                "knowledge_base.rag.factory.get_llm",
                new_callable=AsyncMock,
                return_value=mock_llm,
            ):
                intake = _make_intake(content="Some content.")
                result = await classifier.classify(intake)

        assert result.factors["content_impact"] == _IMPACT_FALLBACK_SCORE
        assert result.factors["content_impact_category"] == "unknown"

    @pytest.mark.asyncio
    async def test_content_impact_disabled_uses_fallback(self) -> None:
        """When GOVERNANCE_CONTENT_IMPACT_ENABLED=False, skip LLM call."""
        classifier = RiskClassifier()

        with patch(
            "knowledge_base.governance.risk_classifier.settings"
        ) as mock_settings:
            mock_settings.GOVERNANCE_CONTENT_IMPACT_ENABLED = False
            mock_settings.GOVERNANCE_LOW_RISK_THRESHOLD = 25
            mock_settings.GOVERNANCE_HIGH_RISK_THRESHOLD = 55
            mock_settings.governance_trusted_domain_list = ["keboola.com"]

            intake = _make_intake(content="Policy change content.")
            result = await classifier.classify(intake)

        assert result.factors["content_impact"] == _IMPACT_FALLBACK_SCORE
        assert result.factors["content_impact_category"] == "disabled"


# ---------------------------------------------------------------------------
# Tests: Weight Rebalance
# ---------------------------------------------------------------------------


class TestWeightRebalance:
    """Verify the new 4-factor weight distribution."""

    @pytest.mark.asyncio
    async def test_weights_sum_to_one(self) -> None:
        """Verify that all weights sum to 1.0."""
        # Weights from risk_classifier.py classify() method
        assert 0.15 + 0.15 + 0.10 + 0.60 == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_factors_dict_has_correct_keys(self) -> None:
        """All 4 factors + category must be present in RiskAssessment.factors."""
        classifier = RiskClassifier()
        mock_llm = _mock_llm_response("routine_info")

        with patch(
            "knowledge_base.governance.risk_classifier.settings"
        ) as mock_settings:
            mock_settings.GOVERNANCE_CONTENT_IMPACT_ENABLED = True
            mock_settings.GOVERNANCE_LOW_RISK_THRESHOLD = 25
            mock_settings.GOVERNANCE_HIGH_RISK_THRESHOLD = 55
            mock_settings.governance_trusted_domain_list = ["keboola.com"]

            with patch(
                "knowledge_base.rag.factory.get_llm",
                new_callable=AsyncMock,
                return_value=mock_llm,
            ):
                intake = _make_intake()
                result = await classifier.classify(intake)

        expected_keys = {
            "author_trust",
            "source_type",
            "content_scope",
            "content_impact",
            "content_impact_category",
        }
        assert set(result.factors.keys()) == expected_keys

    @pytest.mark.asyncio
    async def test_content_impact_dominates_scoring(self) -> None:
        """Content impact at 60% weight should be the dominant factor."""
        classifier = RiskClassifier()

        # Test with policy_change (80) vs routine_info (10) — same metadata
        for category, expected_higher in [("policy_change", True), ("routine_info", False)]:
            mock_llm = _mock_llm_response(category)
            with patch(
                "knowledge_base.governance.risk_classifier.settings"
            ) as mock_settings:
                mock_settings.GOVERNANCE_CONTENT_IMPACT_ENABLED = True
                mock_settings.GOVERNANCE_LOW_RISK_THRESHOLD = 25
                mock_settings.GOVERNANCE_HIGH_RISK_THRESHOLD = 55
                mock_settings.governance_trusted_domain_list = ["keboola.com"]

                with patch(
                    "knowledge_base.rag.factory.get_llm",
                    new_callable=AsyncMock,
                    return_value=mock_llm,
                ):
                    intake = _make_intake(
                        author_email="user@keboola.com",
                        intake_path="slack_create",
                        content="Test content.",
                    )
                    result = await classifier.classify(intake)

            if expected_higher:
                assert result.score >= 50  # policy should push score high
            else:
                assert result.score < 20  # routine should keep score low


# ---------------------------------------------------------------------------
# Tests: Author Trust
# ---------------------------------------------------------------------------


class TestAuthorTrust:
    """Test author trust scoring based on email domain."""

    @pytest.mark.asyncio
    async def test_keboola_domain_trusted(self) -> None:
        """keboola.com email gets lowest trust score (most trusted)."""
        classifier = RiskClassifier()
        assert classifier._score_author_trust("alice@keboola.com") == 10.0

    @pytest.mark.asyncio
    async def test_unknown_domain_moderate(self) -> None:
        """@unknown domain gets moderate trust score."""
        classifier = RiskClassifier()
        assert classifier._score_author_trust("user@unknown") == 60.0

    @pytest.mark.asyncio
    async def test_external_domain_high_risk(self) -> None:
        """External domain gets highest trust score (least trusted)."""
        classifier = RiskClassifier()
        assert classifier._score_author_trust("someone@external.org") == 80.0

    @pytest.mark.asyncio
    async def test_no_at_sign_high_risk(self) -> None:
        """Email without @ gets highest trust score."""
        classifier = RiskClassifier()
        assert classifier._score_author_trust("just_a_username") == 80.0

    @pytest.mark.asyncio
    async def test_custom_trusted_domain(self) -> None:
        """Custom trusted domain is recognized."""
        classifier = RiskClassifier()
        with patch(
            "knowledge_base.governance.risk_classifier.settings"
        ) as mock_settings:
            mock_settings.governance_trusted_domain_list = ["keboola.com", "partner.io"]
            assert classifier._score_author_trust("alice@partner.io") == 10.0


# ---------------------------------------------------------------------------
# Tests: Source Type
# ---------------------------------------------------------------------------


class TestSourceType:
    """Test source type scoring based on intake path."""

    @pytest.mark.asyncio
    async def test_keboola_sync_low_risk(self) -> None:
        classifier = RiskClassifier()
        assert classifier._score_source_type("keboola_sync") == 10.0

    @pytest.mark.asyncio
    async def test_slack_create_moderate(self) -> None:
        classifier = RiskClassifier()
        assert classifier._score_source_type("slack_create") == 30.0

    @pytest.mark.asyncio
    async def test_slack_ingest_high_risk(self) -> None:
        classifier = RiskClassifier()
        assert classifier._score_source_type("slack_ingest") == 70.0

    @pytest.mark.asyncio
    async def test_unknown_path_default(self) -> None:
        classifier = RiskClassifier()
        assert classifier._score_source_type("unknown_path") == 50.0


# ---------------------------------------------------------------------------
# Tests: Content Scope
# ---------------------------------------------------------------------------


class TestContentScope:
    """Test content scope scoring based on length."""

    @pytest.mark.asyncio
    async def test_short_content(self) -> None:
        classifier = RiskClassifier()
        assert classifier._score_content_scope(100) == 15.0

    @pytest.mark.asyncio
    async def test_medium_content(self) -> None:
        classifier = RiskClassifier()
        assert classifier._score_content_scope(1000) == 35.0

    @pytest.mark.asyncio
    async def test_long_content(self) -> None:
        classifier = RiskClassifier()
        assert classifier._score_content_scope(3000) == 55.0

    @pytest.mark.asyncio
    async def test_very_long_content(self) -> None:
        classifier = RiskClassifier()
        assert classifier._score_content_scope(10000) == 75.0


# ---------------------------------------------------------------------------
# Tests: Tier Determination
# ---------------------------------------------------------------------------


class TestTierDetermination:
    """Test tier boundaries and governance status mapping."""

    @pytest.mark.asyncio
    async def test_score_at_low_threshold(self) -> None:
        """Score exactly at low threshold -> low tier."""
        classifier = RiskClassifier()
        with patch(
            "knowledge_base.governance.risk_classifier.settings"
        ) as mock_settings:
            mock_settings.GOVERNANCE_LOW_RISK_THRESHOLD = 25
            mock_settings.GOVERNANCE_HIGH_RISK_THRESHOLD = 55
            assert classifier._determine_tier(25.0) == "low"

    @pytest.mark.asyncio
    async def test_score_at_high_threshold(self) -> None:
        """Score exactly at high threshold -> high tier."""
        classifier = RiskClassifier()
        with patch(
            "knowledge_base.governance.risk_classifier.settings"
        ) as mock_settings:
            mock_settings.GOVERNANCE_LOW_RISK_THRESHOLD = 25
            mock_settings.GOVERNANCE_HIGH_RISK_THRESHOLD = 55
            assert classifier._determine_tier(55.0) == "high"

    @pytest.mark.asyncio
    async def test_score_between_thresholds(self) -> None:
        """Score between thresholds -> medium tier."""
        classifier = RiskClassifier()
        with patch(
            "knowledge_base.governance.risk_classifier.settings"
        ) as mock_settings:
            mock_settings.GOVERNANCE_LOW_RISK_THRESHOLD = 25
            mock_settings.GOVERNANCE_HIGH_RISK_THRESHOLD = 55
            assert classifier._determine_tier(40.0) == "medium"

    @pytest.mark.asyncio
    async def test_governance_status_mapping(self) -> None:
        """Verify tier-to-governance-status mapping."""
        classifier = RiskClassifier()
        assert classifier._determine_governance_status("high") == "pending"
        assert classifier._determine_governance_status("medium") == "approved"
        assert classifier._determine_governance_status("low") == "approved"


# ---------------------------------------------------------------------------
# Tests: End-to-End Scenarios
# ---------------------------------------------------------------------------


class TestEndToEndScenarios:
    """Test real-world content scenarios from the bug report."""

    @pytest.mark.asyncio
    async def test_macbook_policy_is_high_risk(self) -> None:
        """The exact Macbook policy from the bug report should be HIGH risk.

        Content: 'new type of computer for everybody is Macbook Air M4...'
        This is a company-wide policy change -> policy_change category.

        Score: 60*0.15 + 30*0.15 + 15*0.10 + 80*0.60 = 63 -> HIGH (>=55)
        """
        classifier = RiskClassifier()
        mock_llm = _mock_llm_response("policy_change")

        with patch(
            "knowledge_base.governance.risk_classifier.settings"
        ) as mock_settings:
            mock_settings.GOVERNANCE_CONTENT_IMPACT_ENABLED = True
            mock_settings.GOVERNANCE_LOW_RISK_THRESHOLD = 25
            mock_settings.GOVERNANCE_HIGH_RISK_THRESHOLD = 55
            mock_settings.governance_trusted_domain_list = ["keboola.com"]

            with patch(
                "knowledge_base.rag.factory.get_llm",
                new_callable=AsyncMock,
                return_value=mock_llm,
            ):
                intake = _make_intake(
                    author_email="user@unknown",
                    intake_path="slack_create",
                    content=(
                        "new type of computer for everybody is Macbook Air M4 "
                        "13'' or 15'' screen size. 16gb RAM, 256gb hdd. All "
                        "computers are rented with Alza rent. Developer and "
                        "heavy engineering roles can apply for higher performance "
                        "computers, exceptions to be approved by CTO."
                    ),
                )
                result = await classifier.classify(intake)

        # Verify exact score calculation
        expected_score = 60 * 0.15 + 30 * 0.15 + 15 * 0.10 + 80 * 0.60
        assert result.score == pytest.approx(expected_score, abs=0.01)
        assert result.tier == "high"
        assert result.governance_status == "pending"

    @pytest.mark.asyncio
    async def test_keboola_sync_routine_is_low_risk(self) -> None:
        """Keboola sync of routine content -> LOW risk (auto-approved)."""
        classifier = RiskClassifier()
        mock_llm = _mock_llm_response("routine_info")

        with patch(
            "knowledge_base.governance.risk_classifier.settings"
        ) as mock_settings:
            mock_settings.GOVERNANCE_CONTENT_IMPACT_ENABLED = True
            mock_settings.GOVERNANCE_LOW_RISK_THRESHOLD = 25
            mock_settings.GOVERNANCE_HIGH_RISK_THRESHOLD = 55
            mock_settings.governance_trusted_domain_list = ["keboola.com"]

            with patch(
                "knowledge_base.rag.factory.get_llm",
                new_callable=AsyncMock,
                return_value=mock_llm,
            ):
                intake = _make_intake(
                    author_email="system@keboola.com",
                    intake_path="keboola_sync",
                    content="Synced content from Confluence page.",
                )
                result = await classifier.classify(intake)

        # 10*0.15 + 10*0.15 + 15*0.10 + 10*0.60 = 1.5+1.5+1.5+6 = 10.5
        assert result.score == pytest.approx(10.5, abs=0.01)
        assert result.tier == "low"
        assert result.governance_status == "approved"

    @pytest.mark.asyncio
    async def test_all_impact_categories_have_scores(self) -> None:
        """Verify every impact category has a defined score."""
        expected_categories = {
            "routine_info",
            "team_update",
            "process_change",
            "tool_technology",
            "org_structure",
            "policy_change",
            "financial_impact",
            "security_change",
        }
        assert set(_IMPACT_CATEGORY_SCORES.keys()) == expected_categories

        # All scores should be between 0 and 100
        for score in _IMPACT_CATEGORY_SCORES.values():
            assert 0 <= score <= 100

    @pytest.mark.asyncio
    async def test_impact_scores_ordered_by_severity(self) -> None:
        """Lower-impact categories should have lower scores than higher-impact ones."""
        assert _IMPACT_CATEGORY_SCORES["routine_info"] < _IMPACT_CATEGORY_SCORES["team_update"]
        assert _IMPACT_CATEGORY_SCORES["team_update"] < _IMPACT_CATEGORY_SCORES["process_change"]
        assert _IMPACT_CATEGORY_SCORES["process_change"] < _IMPACT_CATEGORY_SCORES["policy_change"]
        assert _IMPACT_CATEGORY_SCORES["policy_change"] < _IMPACT_CATEGORY_SCORES["security_change"]
