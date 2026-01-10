"""Knowledge lifecycle management module.

This module handles:
- Quality scoring and usage-based decay
- User feedback collection and processing
- Two-stage archival pipeline (cold storage -> hard archive)
- AI-assisted conflict detection and resolution
"""

from knowledge_base.lifecycle.archival import (
    deprecate_chunk,
    export_to_hard_archive,
    get_archival_stats,
    get_cold_archived_chunks_older_than,
    move_to_cold_storage,
    run_archival_pipeline,
)
from knowledge_base.lifecycle.conflicts import (
    detect_conflicts_for_chunk,
    dismiss_conflict,
    get_conflict_stats,
    get_conflict_with_chunks,
    get_open_conflicts,
    report_conflict,
    resolve_conflict,
    run_conflict_detection_batch,
)
from knowledge_base.lifecycle.feedback import (
    get_feedback_for_chunk,
    get_feedback_stats,
    get_high_impact_feedback,
    get_unreviewed_feedback,
    review_feedback,
    submit_feedback,
)
from knowledge_base.lifecycle.quality import (
    calculate_usage_adjusted_decay,
    cleanup_old_access_logs,
    initialize_all_chunk_quality,
    initialize_chunk_quality,
    recalculate_quality_scores,
    record_chunk_access,
    update_rolling_access_counts,
)
from knowledge_base.lifecycle.scorer import (
    apply_quality_boost,
    calculate_chunk_quality_score,
    get_quality_scores_for_chunks,
    get_quality_stats,
)
from knowledge_base.lifecycle.signals import (
    get_signal_analyzer,
    get_signal_stats,
    get_signals_for_chunks,
    process_reaction,
    process_thread_message,
    record_bot_response,
    record_signal,
)

__all__ = [
    # Quality
    "calculate_usage_adjusted_decay",
    "cleanup_old_access_logs",
    "initialize_all_chunk_quality",
    "initialize_chunk_quality",
    "recalculate_quality_scores",
    "record_chunk_access",
    "update_rolling_access_counts",
    # Scoring (Phase 11)
    "apply_quality_boost",
    "calculate_chunk_quality_score",
    "get_quality_scores_for_chunks",
    "get_quality_stats",
    # Behavioral Signals (Phase 10.5)
    "get_signal_analyzer",
    "get_signal_stats",
    "get_signals_for_chunks",
    "process_reaction",
    "process_thread_message",
    "record_bot_response",
    "record_signal",
    # Feedback
    "get_feedback_for_chunk",
    "get_feedback_stats",
    "get_high_impact_feedback",
    "get_unreviewed_feedback",
    "review_feedback",
    "submit_feedback",
    # Archival
    "deprecate_chunk",
    "export_to_hard_archive",
    "get_archival_stats",
    "get_cold_archived_chunks_older_than",
    "move_to_cold_storage",
    "run_archival_pipeline",
    # Conflicts
    "detect_conflicts_for_chunk",
    "dismiss_conflict",
    "get_conflict_stats",
    "get_conflict_with_chunks",
    "get_open_conflicts",
    "report_conflict",
    "resolve_conflict",
    "run_conflict_detection_batch",
]
