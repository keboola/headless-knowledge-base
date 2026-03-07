"""Governance module for content quality management."""

from knowledge_base.governance.approval_engine import ApprovalEngine, GovernanceResult
from knowledge_base.governance.gap_analyzer import GapAnalyzer, GapInfo, QueryCluster
from knowledge_base.governance.obsolete_detector import (
    FeedbackStats,
    ObsoleteDetector,
    ObsoleteDocument,
)
from knowledge_base.governance.reports import (
    GovernanceReport,
    GovernanceReporter,
    SpaceStats,
    TopicCoverage,
)
from knowledge_base.governance.risk_classifier import (
    IntakeRequest,
    RiskAssessment,
    RiskClassifier,
)

__all__ = [
    "ApprovalEngine",
    "FeedbackStats",
    "GapAnalyzer",
    "GapInfo",
    "GovernanceReport",
    "GovernanceReporter",
    "GovernanceResult",
    "IntakeRequest",
    "ObsoleteDetector",
    "ObsoleteDocument",
    "QueryCluster",
    "RiskAssessment",
    "RiskClassifier",
    "SpaceStats",
    "TopicCoverage",
]
