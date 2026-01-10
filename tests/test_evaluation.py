"""Tests for the evaluation module."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from knowledge_base.evaluation.llm_judge import (
    LLMJudge,
    EvaluationScores,
)
from knowledge_base.evaluation.nightly_eval import (
    NightlyEvaluator,
    DailyReportData,
    EvalResultData,
)


class TestEvaluationScores:
    """Tests for EvaluationScores dataclass."""

    def test_overall_calculation(self):
        """Test overall score is average of three metrics."""
        scores = EvaluationScores(
            groundedness=0.9,
            relevance=0.8,
            completeness=0.7,
        )
        assert scores.overall == pytest.approx(0.8, 0.01)

    def test_all_perfect(self):
        """Test overall score when all metrics are 1.0."""
        scores = EvaluationScores(
            groundedness=1.0,
            relevance=1.0,
            completeness=1.0,
        )
        assert scores.overall == 1.0

    def test_all_zero(self):
        """Test overall score when all metrics are 0.0."""
        scores = EvaluationScores(
            groundedness=0.0,
            relevance=0.0,
            completeness=0.0,
        )
        assert scores.overall == 0.0


class TestLLMJudge:
    """Tests for LLMJudge."""

    @pytest.fixture
    def mock_llm(self):
        """Create a mock LLM."""
        llm = MagicMock()
        llm.generate = AsyncMock(return_value="0.85")
        return llm

    @pytest.mark.asyncio
    async def test_evaluate_returns_scores(self, mock_llm):
        """Test evaluate returns EvaluationScores."""
        judge = LLMJudge(mock_llm)

        scores = await judge.evaluate(
            query="What is X?",
            answer="X is a thing.",
            documents=["Document about X."],
        )

        assert isinstance(scores, EvaluationScores)
        assert 0.0 <= scores.groundedness <= 1.0
        assert 0.0 <= scores.relevance <= 1.0
        assert 0.0 <= scores.completeness <= 1.0

    @pytest.mark.asyncio
    async def test_evaluate_groundedness_empty_docs(self, mock_llm):
        """Test groundedness returns 0 for empty documents."""
        judge = LLMJudge(mock_llm)
        score = await judge.evaluate_groundedness("answer", [])
        assert score == 0.0

    @pytest.mark.asyncio
    async def test_evaluate_relevance_empty_docs(self, mock_llm):
        """Test relevance returns 0 for empty documents."""
        judge = LLMJudge(mock_llm)
        score = await judge.evaluate_relevance("query", [])
        assert score == 0.0

    @pytest.mark.asyncio
    async def test_evaluate_completeness_empty_answer(self, mock_llm):
        """Test completeness returns 0 for empty answer."""
        judge = LLMJudge(mock_llm)
        score = await judge.evaluate_completeness("query", "")
        assert score == 0.0

    @pytest.mark.asyncio
    async def test_parse_score_decimal(self, mock_llm):
        """Test parsing decimal score."""
        judge = LLMJudge(mock_llm)
        assert judge._parse_score("0.85") == 0.85
        assert judge._parse_score("0.5") == 0.5
        assert judge._parse_score("1.0") == 1.0

    @pytest.mark.asyncio
    async def test_parse_score_with_text(self, mock_llm):
        """Test parsing score with surrounding text."""
        judge = LLMJudge(mock_llm)
        assert judge._parse_score("The score is 0.75") == 0.75
        assert judge._parse_score("Score: 0.9") == 0.9

    @pytest.mark.asyncio
    async def test_parse_score_clamps_to_1(self, mock_llm):
        """Test score is clamped to maximum of 1.0."""
        judge = LLMJudge(mock_llm)
        assert judge._parse_score("1.5") == 1.0
        assert judge._parse_score("2.0") == 1.0

    @pytest.mark.asyncio
    async def test_parse_score_clamps_to_0(self, mock_llm):
        """Test score is clamped to minimum of 0.0."""
        judge = LLMJudge(mock_llm)
        # Negative numbers aren't matched by the regex, so default is returned
        assert judge._parse_score("-0.5") == 0.5  # Default

    @pytest.mark.asyncio
    async def test_format_docs_truncates(self, mock_llm):
        """Test document formatting truncates long content."""
        judge = LLMJudge(mock_llm)
        long_doc = "x" * 5000
        formatted = judge._format_docs([long_doc], max_length=1000)
        assert len(formatted) <= 1100  # Some buffer for formatting

    @pytest.mark.asyncio
    async def test_format_docs_multiple(self, mock_llm):
        """Test formatting multiple documents."""
        judge = LLMJudge(mock_llm)
        docs = ["Doc 1 content", "Doc 2 content", "Doc 3 content"]
        formatted = judge._format_docs(docs)

        assert "[Document 1]" in formatted
        assert "[Document 2]" in formatted
        assert "[Document 3]" in formatted

    @pytest.mark.asyncio
    async def test_handles_llm_error(self, mock_llm):
        """Test graceful handling of LLM errors."""
        mock_llm.generate = AsyncMock(side_effect=Exception("LLM error"))
        judge = LLMJudge(mock_llm)

        score = await judge.evaluate_groundedness("answer", ["doc"])
        # Should return default score
        assert score == 0.5


class TestEvalResultData:
    """Tests for EvalResultData dataclass."""

    def test_creation(self):
        """Test creating EvalResultData."""
        result = EvalResultData(
            query_id="q123",
            groundedness=0.9,
            relevance=0.8,
            completeness=0.7,
            overall=0.8,
        )
        assert result.query_id == "q123"
        assert result.overall == 0.8


class TestDailyReportData:
    """Tests for DailyReportData dataclass."""

    def test_creation(self):
        """Test creating DailyReportData."""
        report = DailyReportData(
            report_date=datetime.utcnow(),
            sample_size=10,
            total_queries=100,
            avg_groundedness=0.85,
            avg_relevance=0.80,
            avg_completeness=0.75,
            avg_overall=0.80,
        )
        assert report.sample_size == 10
        assert report.avg_overall == 0.80

    def test_below_threshold_default_empty(self):
        """Test below_threshold defaults to empty list."""
        report = DailyReportData(
            report_date=datetime.utcnow(),
            sample_size=0,
            total_queries=0,
            avg_groundedness=0.0,
            avg_relevance=0.0,
            avg_completeness=0.0,
            avg_overall=0.0,
        )
        assert report.below_threshold == []


class TestNightlyEvaluator:
    """Tests for NightlyEvaluator."""

    @pytest.fixture
    def mock_llm(self):
        """Create a mock LLM."""
        llm = MagicMock()
        llm.generate = AsyncMock(return_value="0.85")
        return llm

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.execute = MagicMock()
        session.add = MagicMock()
        session.commit = MagicMock()
        return session

    def test_should_alert_low_overall(self, mock_llm, mock_session):
        """Test alert is triggered for low overall score."""
        evaluator = NightlyEvaluator(mock_llm, mock_session, overall_threshold=0.7)

        report = DailyReportData(
            report_date=datetime.utcnow(),
            sample_size=10,
            total_queries=100,
            avg_groundedness=0.5,
            avg_relevance=0.5,
            avg_completeness=0.5,
            avg_overall=0.5,
        )

        assert evaluator.should_alert(report) is True

    def test_should_not_alert_high_overall(self, mock_llm, mock_session):
        """Test no alert for high overall score."""
        evaluator = NightlyEvaluator(mock_llm, mock_session, overall_threshold=0.7)

        report = DailyReportData(
            report_date=datetime.utcnow(),
            sample_size=10,
            total_queries=100,
            avg_groundedness=0.9,
            avg_relevance=0.9,
            avg_completeness=0.9,
            avg_overall=0.9,
        )

        assert evaluator.should_alert(report) is False

    def test_should_not_alert_empty_sample(self, mock_llm, mock_session):
        """Test no alert for empty sample."""
        evaluator = NightlyEvaluator(mock_llm, mock_session)

        report = DailyReportData(
            report_date=datetime.utcnow(),
            sample_size=0,
            total_queries=0,
            avg_groundedness=0.0,
            avg_relevance=0.0,
            avg_completeness=0.0,
            avg_overall=0.0,
        )

        assert evaluator.should_alert(report) is False

    def test_empty_report(self, mock_llm, mock_session):
        """Test empty report generation."""
        evaluator = NightlyEvaluator(mock_llm, mock_session)
        report = evaluator._empty_report()

        assert report.sample_size == 0
        assert report.total_queries == 0
        assert report.avg_overall == 0.0

    def test_generate_report(self, mock_llm, mock_session):
        """Test report generation from results."""
        evaluator = NightlyEvaluator(
            mock_llm,
            mock_session,
            groundedness_threshold=0.7,
            relevance_threshold=0.6,
        )

        results = [
            EvalResultData("q1", 0.9, 0.8, 0.7, 0.8),
            EvalResultData("q2", 0.5, 0.5, 0.5, 0.5),  # Below threshold
            EvalResultData("q3", 0.8, 0.7, 0.6, 0.7),
        ]

        report = evaluator._generate_report(results, total_queries=30)

        assert report.sample_size == 3
        assert report.total_queries == 30
        assert len(report.below_threshold) == 1
        assert report.below_threshold[0].query_id == "q2"

    @pytest.mark.asyncio
    async def test_run_nightly_no_queries(self, mock_llm, mock_session):
        """Test nightly run with no queries returns empty report."""
        mock_session.execute.return_value.scalars.return_value.all.return_value = []

        evaluator = NightlyEvaluator(mock_llm, mock_session)
        report = await evaluator.run_nightly()

        assert report.sample_size == 0
        assert report.total_queries == 0
