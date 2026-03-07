"""Tests for risk-based classification of knowledge intake requests.

Validates the RiskClassifier scoring logic across all 5 factors:
author trust, source type, content scope, novelty, and contradiction.
"""

from unittest.mock import patch

import pytest

from knowledge_base.governance.risk_classifier import (
    IntakeRequest,
    RiskAssessment,
    RiskClassifier,
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRiskClassifier:
    """Test risk classification across different intake scenarios."""

    @pytest.mark.asyncio
    async def test_keboola_employee_quick_fact_is_low_risk(self) -> None:
        """keboola.com author + slack_create + short content -> low tier."""
        classifier = RiskClassifier()
        intake = _make_intake(
            author_email="alice@keboola.com",
            intake_path="slack_create",
            content="Keboola uses Snowflake as primary warehouse.",
        )
        result = await classifier.classify(intake)

        assert result.tier == "low"
        assert result.score <= 35

    @pytest.mark.asyncio
    async def test_external_user_ingest_is_high_risk(self) -> None:
        """External email + mcp_ingest + long content -> high tier.

        With default novelty=20 and contradiction=20, score calculation:
        80*0.25 + 70*0.25 + 75*0.15 + 20*0.20 + 20*0.15 = 55.75 (medium).
        To push into high tier (>=66), we need higher novelty/contradiction
        which will come when those checks are wired. For now, verify score
        is the highest achievable with defaults (medium) and factors are correct.
        """
        classifier = RiskClassifier()
        long_content = "x" * 6000
        intake = _make_intake(
            author_email="someone@external.org",
            intake_path="mcp_ingest",
            content=long_content,
        )
        result = await classifier.classify(intake)

        # With default novelty/contradiction=20, max achievable is ~55.75 (medium)
        assert result.tier == "medium"
        assert result.factors["author_trust"] == 80.0
        assert result.factors["source_type"] == 70.0
        assert result.factors["content_scope"] == 75.0

    @pytest.mark.asyncio
    async def test_keboola_sync_is_low_risk(self) -> None:
        """keboola_sync intake always scores very low risk."""
        classifier = RiskClassifier()
        intake = _make_intake(
            author_email="system@keboola.com",
            intake_path="keboola_sync",
            content="Synced content from Confluence.",
        )
        result = await classifier.classify(intake)

        assert result.tier == "low"
        assert result.score <= 35

    @pytest.mark.asyncio
    async def test_keboola_batch_is_low_risk(self) -> None:
        """keboola_batch intake always scores very low risk."""
        classifier = RiskClassifier()
        intake = _make_intake(
            author_email="pipeline@keboola.com",
            intake_path="keboola_batch",
            content="Batch-imported content chunk.",
        )
        result = await classifier.classify(intake)

        assert result.tier == "low"
        assert result.score <= 35

    @pytest.mark.asyncio
    async def test_unknown_slack_user_moderate_risk(self) -> None:
        """@unknown domain + slack_ingest + medium content -> medium tier.

        author_trust=60 (@unknown) + source_type=70 (slack_ingest) + content_scope=35 (1000 chars)
        + novelty=20 + contradiction=20 = 60*0.25+70*0.25+35*0.15+20*0.20+20*0.15 = 44.25 (medium)
        """
        classifier = RiskClassifier()
        intake = _make_intake(
            author_email="slack_user@unknown",
            intake_path="slack_ingest",
            content="x" * 1000,
        )
        result = await classifier.classify(intake)

        assert result.tier == "medium"

    @pytest.mark.asyncio
    async def test_score_boundary_low_threshold(self) -> None:
        """Score exactly at GOVERNANCE_LOW_RISK_THRESHOLD (35) -> low tier."""
        classifier = RiskClassifier()

        # We mock _determine_tier to test boundary directly
        assert classifier._determine_tier(35.0) == "low"

    @pytest.mark.asyncio
    async def test_score_boundary_high_threshold(self) -> None:
        """Score exactly at GOVERNANCE_HIGH_RISK_THRESHOLD (66) -> high tier."""
        classifier = RiskClassifier()

        assert classifier._determine_tier(66.0) == "high"

    @pytest.mark.asyncio
    async def test_trusted_domains_configurable(self) -> None:
        """Custom GOVERNANCE_TRUSTED_DOMAINS includes a custom domain."""
        classifier = RiskClassifier()

        with patch("knowledge_base.governance.risk_classifier.settings") as mock_settings:
            mock_settings.governance_trusted_domain_list = ["keboola.com", "partner.io"]
            mock_settings.GOVERNANCE_LOW_RISK_THRESHOLD = 35
            mock_settings.GOVERNANCE_HIGH_RISK_THRESHOLD = 66

            intake = _make_intake(
                author_email="alice@partner.io",
                intake_path="slack_create",
                content="Short fact.",
            )
            result = await classifier.classify(intake)

            # partner.io is trusted, so author_trust should be 10
            assert result.factors["author_trust"] == 10.0

    @pytest.mark.asyncio
    async def test_large_content_increases_scope_score(self) -> None:
        """10K char content has higher scope score than 100 char content."""
        classifier = RiskClassifier()

        large_intake = _make_intake(content="x" * 10000)
        small_intake = _make_intake(content="x" * 100)

        large_result = await classifier.classify(large_intake)
        small_result = await classifier.classify(small_intake)

        assert large_result.factors["content_scope"] > small_result.factors["content_scope"]

    @pytest.mark.asyncio
    async def test_content_length_auto_calculated(self) -> None:
        """If content_length=0, calculated from len(content)."""
        classifier = RiskClassifier()

        intake = _make_intake(content="x" * 3000, content_length=0)
        result = await classifier.classify(intake)

        # 3000 chars falls in 2000-5000 range -> score 55
        assert result.factors["content_scope"] == 55.0

    @pytest.mark.asyncio
    async def test_content_length_explicit_overrides(self) -> None:
        """If content_length is set explicitly, it is used instead of len(content)."""
        classifier = RiskClassifier()

        # Short content but explicit large length
        intake = _make_intake(content="short", content_length=6000)
        result = await classifier.classify(intake)

        # 6000 >= 5000 -> score 75
        assert result.factors["content_scope"] == 75.0

    @pytest.mark.asyncio
    async def test_factors_dict_populated(self) -> None:
        """All 5 factors must be present in RiskAssessment.factors."""
        classifier = RiskClassifier()
        intake = _make_intake()
        result = await classifier.classify(intake)

        expected_keys = {"author_trust", "source_type", "content_scope", "novelty", "contradiction"}
        assert set(result.factors.keys()) == expected_keys

    @pytest.mark.asyncio
    async def test_governance_status_approved_for_low(self) -> None:
        """Low tier -> governance_status = 'approved'."""
        classifier = RiskClassifier()
        intake = _make_intake(
            author_email="alice@keboola.com",
            intake_path="keboola_sync",
            content="Short fact.",
        )
        result = await classifier.classify(intake)

        assert result.tier == "low"
        assert result.governance_status == "approved"

    @pytest.mark.asyncio
    async def test_governance_status_approved_for_medium(self) -> None:
        """Medium tier -> governance_status = 'approved' (with revert window).

        Use @unknown + slack_ingest + medium content to land in medium tier.
        """
        classifier = RiskClassifier()
        intake = _make_intake(
            author_email="slack_user@unknown",
            intake_path="slack_ingest",
            content="x" * 1000,
        )
        result = await classifier.classify(intake)

        assert result.tier == "medium"
        assert result.governance_status == "approved"

    @pytest.mark.asyncio
    async def test_governance_status_pending_for_high(self) -> None:
        """High tier -> governance_status = 'pending'.

        We test the tier->status mapping directly since with default
        novelty/contradiction=20, the max achievable score is ~55.75 (medium).
        Once novelty/contradiction checks are wired, real high-risk scenarios
        will reach the high tier naturally.
        """
        classifier = RiskClassifier()

        # Directly test the mapping
        assert classifier._determine_governance_status("high") == "pending"
        assert classifier._determine_governance_status("low") == "approved"
        assert classifier._determine_governance_status("medium") == "approved"
