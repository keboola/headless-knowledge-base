"""Nightly evaluation job for RAG quality monitoring."""

import json
import logging
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from knowledge_base.db.models import EvalResult, QualityReport, QueryRecord
from knowledge_base.evaluation.llm_judge import EvaluationScores, LLMJudge

if TYPE_CHECKING:
    from knowledge_base.rag.llm import BaseLLM

logger = logging.getLogger(__name__)

# Default thresholds for quality alerts
DEFAULT_GROUNDEDNESS_THRESHOLD = 0.7
DEFAULT_RELEVANCE_THRESHOLD = 0.6
DEFAULT_OVERALL_THRESHOLD = 0.7


@dataclass
class EvalResultData:
    """Evaluation result for a single query."""

    query_id: str
    groundedness: float
    relevance: float
    completeness: float
    overall: float


@dataclass
class DailyReportData:
    """Daily quality report data."""

    report_date: datetime
    sample_size: int
    total_queries: int
    avg_groundedness: float
    avg_relevance: float
    avg_completeness: float
    avg_overall: float
    below_threshold: list[EvalResultData] = field(default_factory=list)


class NightlyEvaluator:
    """Run nightly evaluation on sampled queries."""

    def __init__(
        self,
        llm: "BaseLLM",
        session: Session,
        groundedness_threshold: float = DEFAULT_GROUNDEDNESS_THRESHOLD,
        relevance_threshold: float = DEFAULT_RELEVANCE_THRESHOLD,
        overall_threshold: float = DEFAULT_OVERALL_THRESHOLD,
    ):
        """Initialize nightly evaluator.

        Args:
            llm: LLM for evaluation
            session: Database session
            groundedness_threshold: Minimum groundedness score
            relevance_threshold: Minimum relevance score
            overall_threshold: Minimum overall score for alert
        """
        self.judge = LLMJudge(llm)
        self.session = session
        self.groundedness_threshold = groundedness_threshold
        self.relevance_threshold = relevance_threshold
        self.overall_threshold = overall_threshold

    async def run_nightly(
        self,
        sample_rate: float = 0.1,
        max_samples: int = 100,
        lookback_hours: int = 24,
    ) -> DailyReportData:
        """Run nightly evaluation on sample of recent queries.

        Args:
            sample_rate: Fraction of queries to sample (0.0 to 1.0)
            max_samples: Maximum number of samples to evaluate
            lookback_hours: Hours to look back for queries

        Returns:
            DailyReportData with evaluation results
        """
        batch_id = str(uuid.uuid4())[:8]
        logger.info(f"Starting nightly evaluation batch {batch_id}")

        # Get queries from lookback period
        since = datetime.utcnow() - timedelta(hours=lookback_hours)
        queries = self._get_unevaluated_queries(since)

        total_queries = len(queries)
        logger.info(f"Found {total_queries} unevaluated queries")

        if not queries:
            return self._empty_report()

        # Sample queries
        sample_size = min(int(len(queries) * sample_rate), max_samples)
        sample_size = max(sample_size, 1)  # At least 1

        sample = random.sample(queries, min(sample_size, len(queries)))
        logger.info(f"Sampled {len(sample)} queries for evaluation")

        # Evaluate each query
        results: list[EvalResultData] = []
        for query_record in sample:
            try:
                result = await self._evaluate_query(query_record, batch_id)
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to evaluate query {query_record.query_id}: {e}")

        if not results:
            return self._empty_report()

        # Generate report
        report = self._generate_report(results, total_queries)

        # Save report to database
        self._save_report(report)

        logger.info(
            f"Nightly evaluation complete: {report.avg_overall:.2f} overall "
            f"({len(report.below_threshold)} below threshold)"
        )

        return report

    def _get_unevaluated_queries(self, since: datetime) -> list[QueryRecord]:
        """Get unevaluated queries since given time."""
        stmt = (
            select(QueryRecord)
            .where(QueryRecord.created_at >= since)
            .where(QueryRecord.evaluated == False)  # noqa: E712
            .order_by(QueryRecord.created_at.desc())
        )
        return list(self.session.execute(stmt).scalars().all())

    async def _evaluate_query(
        self, record: QueryRecord, batch_id: str
    ) -> EvalResultData:
        """Evaluate a single query record.

        Args:
            record: Query record to evaluate
            batch_id: Current evaluation batch ID

        Returns:
            EvalResultData with scores
        """
        # Parse retrieved documents
        try:
            documents = json.loads(record.retrieved_docs_content or "[]")
        except json.JSONDecodeError:
            documents = []

        # Evaluate with LLM judge
        scores = await self.judge.evaluate(
            query=record.query,
            answer=record.answer,
            documents=documents,
        )

        # Save result to database
        eval_result = EvalResult(
            query_id=record.query_id,
            groundedness=scores.groundedness,
            relevance=scores.relevance,
            completeness=scores.completeness,
            overall=scores.overall,
            eval_batch_id=batch_id,
        )
        self.session.add(eval_result)

        # Mark query as evaluated
        self.session.execute(
            update(QueryRecord)
            .where(QueryRecord.query_id == record.query_id)
            .values(evaluated=True)
        )

        self.session.commit()

        return EvalResultData(
            query_id=record.query_id,
            groundedness=scores.groundedness,
            relevance=scores.relevance,
            completeness=scores.completeness,
            overall=scores.overall,
        )

    def _generate_report(
        self, results: list[EvalResultData], total_queries: int
    ) -> DailyReportData:
        """Generate daily report from evaluation results."""
        # Calculate averages
        avg_groundedness = sum(r.groundedness for r in results) / len(results)
        avg_relevance = sum(r.relevance for r in results) / len(results)
        avg_completeness = sum(r.completeness for r in results) / len(results)
        avg_overall = sum(r.overall for r in results) / len(results)

        # Find below-threshold results
        below_threshold = [
            r
            for r in results
            if (
                r.groundedness < self.groundedness_threshold
                or r.relevance < self.relevance_threshold
            )
        ]

        return DailyReportData(
            report_date=datetime.utcnow(),
            sample_size=len(results),
            total_queries=total_queries,
            avg_groundedness=avg_groundedness,
            avg_relevance=avg_relevance,
            avg_completeness=avg_completeness,
            avg_overall=avg_overall,
            below_threshold=below_threshold,
        )

    def _save_report(self, report: DailyReportData) -> QualityReport:
        """Save report to database."""
        db_report = QualityReport(
            report_date=report.report_date,
            sample_size=report.sample_size,
            total_queries=report.total_queries,
            avg_groundedness=report.avg_groundedness,
            avg_relevance=report.avg_relevance,
            avg_completeness=report.avg_completeness,
            avg_overall=report.avg_overall,
            below_threshold_count=len(report.below_threshold),
            alert_sent=False,
        )

        self.session.add(db_report)
        self.session.commit()

        return db_report

    def _empty_report(self) -> DailyReportData:
        """Generate empty report when no queries to evaluate."""
        return DailyReportData(
            report_date=datetime.utcnow(),
            sample_size=0,
            total_queries=0,
            avg_groundedness=0.0,
            avg_relevance=0.0,
            avg_completeness=0.0,
            avg_overall=0.0,
        )

    def get_recent_reports(self, days: int = 7) -> list[QualityReport]:
        """Get quality reports from recent days.

        Args:
            days: Number of days to look back

        Returns:
            List of quality reports
        """
        since = datetime.utcnow() - timedelta(days=days)
        stmt = (
            select(QualityReport)
            .where(QualityReport.report_date >= since)
            .order_by(QualityReport.report_date.desc())
        )
        return list(self.session.execute(stmt).scalars().all())

    def should_alert(self, report: DailyReportData) -> bool:
        """Check if report warrants an alert.

        Args:
            report: Daily report data

        Returns:
            True if alert should be sent
        """
        if report.sample_size == 0:
            return False

        return report.avg_overall < self.overall_threshold
