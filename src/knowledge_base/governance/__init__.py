"""Governance module for content quality management."""

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

__all__ = [
    "FeedbackStats",
    "GapAnalyzer",
    "GapInfo",
    "GovernanceReport",
    "GovernanceReporter",
    "ObsoleteDetector",
    "ObsoleteDocument",
    "QueryCluster",
    "SpaceStats",
    "TopicCoverage",
]
