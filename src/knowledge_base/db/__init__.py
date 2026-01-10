"""Database module for knowledge base.

ARCHITECTURE NOTE (per docs/ARCHITECTURE.md):
- ChromaDB is the SOURCE OF TRUTH for knowledge data
- SQLite stores legacy models (being phased out)
- DuckDB stores analytics data (UserFeedback, BehavioralSignal, etc.)
"""

from knowledge_base.db.database import async_session_maker, engine, init_db
# NOTE: GovernanceMetadata is DEPRECATED - data now in ChromaDB
from knowledge_base.db.models import Base, GovernanceMetadata, RawPage

# DuckDB analytics functions (optional - graceful degradation if not installed)
try:
    from knowledge_base.db.duckdb_schema import (
        get_duckdb_connection,
        init_duckdb_schema,
        insert_feedback,
        insert_behavioral_signal,
        insert_bot_response,
        log_chunk_access,
        get_feedback_stats,
        get_signal_stats,
        close_duckdb,
    )
    _duckdb_available = True
except ImportError:
    _duckdb_available = False

__all__ = [
    "Base",
    "RawPage",
    "GovernanceMetadata",
    "engine",
    "async_session_maker",
    "init_db",
    # DuckDB exports (if available)
    "get_duckdb_connection",
    "init_duckdb_schema",
    "insert_feedback",
    "insert_behavioral_signal",
    "insert_bot_response",
    "log_chunk_access",
    "get_feedback_stats",
    "get_signal_stats",
    "close_duckdb",
]
