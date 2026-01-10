"""DuckDB schema for analytics tables.

ARCHITECTURE NOTE (per docs/ARCHITECTURE.md):
- ChromaDB is the SOURCE OF TRUTH for knowledge data (chunks, metadata, quality scores)
- DuckDB stores ONLY analytics and feedback data for queries and reporting

This module provides DuckDB table definitions for:
- UserFeedback: User feedback for retraining and quality
- BehavioralSignal: Implicit signals from Slack interactions
- BotResponse: Bot response tracking for signal correlation
- ChunkAccessLog: Usage analytics
- QueryRecord: Query records for evaluation
- EvalResult: LLM-as-judge evaluation results
- QualityReport: Daily quality reports
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# DuckDB connection (lazy initialized)
_duckdb_conn = None


def get_duckdb_connection():
    """Get or create DuckDB connection.

    For local development, uses a file-based DuckDB.
    For GCP deployment, connects to DuckDB server.
    """
    global _duckdb_conn

    if _duckdb_conn is not None:
        return _duckdb_conn

    try:
        import duckdb
        from knowledge_base.config import settings

        if settings.DUCKDB_HOST:
            # GCP deployment: connect to local file-based DuckDB
            # Note: Previously tried remote DuckDB/MotherDuck but it's not needed
            # Analytics data is stored locally in the container
            db_path = Path("/tmp/analytics.duckdb")
            _duckdb_conn = duckdb.connect(str(db_path))
            logger.info(f"Connected to local DuckDB at {db_path} (GCP mode)")
        else:
            # Local development: file-based DuckDB
            db_path = Path(settings.DUCKDB_PATH)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            _duckdb_conn = duckdb.connect(str(db_path))
            logger.info(f"Connected to local DuckDB at {db_path}")

        return _duckdb_conn

    except ImportError:
        logger.warning("DuckDB not installed. Analytics features unavailable.")
        return None


def init_duckdb_schema() -> bool:
    """Initialize DuckDB tables for analytics.

    Returns True if successful, False otherwise.
    """
    conn = get_duckdb_connection()
    if conn is None:
        return False

    try:
        # User Feedback table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_feedback (
                id INTEGER PRIMARY KEY,
                chunk_id VARCHAR NOT NULL,
                slack_user_id VARCHAR NOT NULL,
                slack_username VARCHAR NOT NULL,
                slack_channel_id VARCHAR,
                feedback_type VARCHAR NOT NULL,
                comment TEXT,
                suggested_correction TEXT,
                query_context TEXT,
                conversation_thread_ts VARCHAR,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reviewed BOOLEAN DEFAULT FALSE,
                review_action VARCHAR,
                reviewed_by VARCHAR,
                reviewed_at TIMESTAMP
            )
        """)

        # Behavioral Signals table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS behavioral_signals (
                id INTEGER PRIMARY KEY,
                response_ts VARCHAR NOT NULL,
                thread_ts VARCHAR NOT NULL,
                chunk_ids TEXT DEFAULT '[]',
                slack_user_id VARCHAR NOT NULL,
                signal_type VARCHAR NOT NULL,
                signal_value DOUBLE NOT NULL,
                raw_text TEXT,
                reaction VARCHAR,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Bot Responses table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_responses (
                id INTEGER PRIMARY KEY,
                response_ts VARCHAR UNIQUE NOT NULL,
                thread_ts VARCHAR NOT NULL,
                channel_id VARCHAR NOT NULL,
                user_id VARCHAR NOT NULL,
                query TEXT NOT NULL,
                response_text TEXT NOT NULL,
                chunk_ids TEXT DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                timeout_checked BOOLEAN DEFAULT FALSE,
                has_follow_up BOOLEAN DEFAULT FALSE
            )
        """)

        # Chunk Access Log table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chunk_access_log (
                id INTEGER PRIMARY KEY,
                chunk_id VARCHAR NOT NULL,
                slack_user_id VARCHAR NOT NULL,
                accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                query_context TEXT
            )
        """)

        # Query Records table (for evaluation)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS query_records (
                id INTEGER PRIMARY KEY,
                query_id VARCHAR UNIQUE NOT NULL,
                query TEXT NOT NULL,
                answer TEXT NOT NULL,
                retrieved_chunks TEXT DEFAULT '[]',
                retrieved_docs_content TEXT DEFAULT '[]',
                slack_user_id VARCHAR,
                channel_id VARCHAR,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                evaluated BOOLEAN DEFAULT FALSE
            )
        """)

        # Evaluation Results table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS eval_results (
                id INTEGER PRIMARY KEY,
                query_id VARCHAR NOT NULL,
                groundedness DOUBLE NOT NULL,
                relevance DOUBLE NOT NULL,
                completeness DOUBLE NOT NULL,
                overall DOUBLE NOT NULL,
                evaluated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                eval_batch_id VARCHAR
            )
        """)

        # Quality Reports table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS quality_reports (
                id INTEGER PRIMARY KEY,
                report_date TIMESTAMP UNIQUE NOT NULL,
                sample_size INTEGER NOT NULL,
                total_queries INTEGER NOT NULL,
                avg_groundedness DOUBLE NOT NULL,
                avg_relevance DOUBLE NOT NULL,
                avg_completeness DOUBLE NOT NULL,
                avg_overall DOUBLE NOT NULL,
                below_threshold_count INTEGER DEFAULT 0,
                alert_sent BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create indexes for common queries
        conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_chunk ON user_feedback(chunk_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_type ON user_feedback(feedback_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_created ON user_feedback(created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_response ON behavioral_signals(response_ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_type ON behavioral_signals(signal_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_access_chunk ON chunk_access_log(chunk_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_access_time ON chunk_access_log(accessed_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_query_created ON query_records(created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_eval_query ON eval_results(query_id)")

        logger.info("DuckDB schema initialized successfully")
        return True

    except Exception as e:
        logger.error(f"Failed to initialize DuckDB schema: {e}")
        return False


async def insert_feedback(
    chunk_id: str,
    slack_user_id: str,
    slack_username: str,
    feedback_type: str,
    comment: str | None = None,
    suggested_correction: str | None = None,
    query_context: str | None = None,
    slack_channel_id: str | None = None,
    thread_ts: str | None = None,
) -> int | None:
    """Insert a feedback record into DuckDB.

    Returns the inserted row ID or None if failed.
    """
    conn = get_duckdb_connection()
    if conn is None:
        return None

    try:
        result = conn.execute("""
            INSERT INTO user_feedback (
                chunk_id, slack_user_id, slack_username, slack_channel_id,
                feedback_type, comment, suggested_correction, query_context,
                conversation_thread_ts, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
        """, [
            chunk_id, slack_user_id, slack_username, slack_channel_id,
            feedback_type, comment, suggested_correction, query_context,
            thread_ts, datetime.utcnow()
        ])
        row = result.fetchone()
        return row[0] if row else None
    except Exception as e:
        logger.error(f"Failed to insert feedback: {e}")
        return None


async def insert_behavioral_signal(
    response_ts: str,
    thread_ts: str,
    chunk_ids: list[str],
    slack_user_id: str,
    signal_type: str,
    signal_value: float,
    raw_text: str | None = None,
    reaction: str | None = None,
) -> int | None:
    """Insert a behavioral signal into DuckDB.

    Returns the inserted row ID or None if failed.
    """
    import json

    conn = get_duckdb_connection()
    if conn is None:
        return None

    try:
        result = conn.execute("""
            INSERT INTO behavioral_signals (
                response_ts, thread_ts, chunk_ids, slack_user_id,
                signal_type, signal_value, raw_text, reaction, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
        """, [
            response_ts, thread_ts, json.dumps(chunk_ids), slack_user_id,
            signal_type, signal_value, raw_text, reaction, datetime.utcnow()
        ])
        row = result.fetchone()
        return row[0] if row else None
    except Exception as e:
        logger.error(f"Failed to insert behavioral signal: {e}")
        return None


async def insert_bot_response(
    response_ts: str,
    thread_ts: str,
    channel_id: str,
    user_id: str,
    query: str,
    response_text: str,
    chunk_ids: list[str],
) -> int | None:
    """Insert a bot response record into DuckDB.

    Returns the inserted row ID or None if failed.
    """
    import json

    conn = get_duckdb_connection()
    if conn is None:
        return None

    try:
        result = conn.execute("""
            INSERT INTO bot_responses (
                response_ts, thread_ts, channel_id, user_id,
                query, response_text, chunk_ids, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
        """, [
            response_ts, thread_ts, channel_id, user_id,
            query, response_text, json.dumps(chunk_ids), datetime.utcnow()
        ])
        row = result.fetchone()
        return row[0] if row else None
    except Exception as e:
        logger.error(f"Failed to insert bot response: {e}")
        return None


async def log_chunk_access(
    chunk_id: str,
    slack_user_id: str,
    query_context: str | None = None,
) -> int | None:
    """Log a chunk access for usage analytics.

    Returns the inserted row ID or None if failed.
    """
    conn = get_duckdb_connection()
    if conn is None:
        return None

    try:
        result = conn.execute("""
            INSERT INTO chunk_access_log (chunk_id, slack_user_id, accessed_at, query_context)
            VALUES (?, ?, ?, ?)
            RETURNING id
        """, [chunk_id, slack_user_id, datetime.utcnow(), query_context])
        row = result.fetchone()
        return row[0] if row else None
    except Exception as e:
        logger.error(f"Failed to log chunk access: {e}")
        return None


def get_feedback_stats(days: int = 30) -> dict[str, Any]:
    """Get feedback statistics for the last N days."""
    conn = get_duckdb_connection()
    if conn is None:
        return {}

    try:
        result = conn.execute("""
            SELECT
                feedback_type,
                COUNT(*) as count
            FROM user_feedback
            WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL ? DAY
            GROUP BY feedback_type
        """, [days])

        by_type = {row[0]: row[1] for row in result.fetchall()}

        total_result = conn.execute("""
            SELECT COUNT(*) FROM user_feedback
            WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL ? DAY
        """, [days])
        total = total_result.fetchone()[0]

        return {
            "total": total,
            "by_type": by_type,
            "days": days,
        }
    except Exception as e:
        logger.error(f"Failed to get feedback stats: {e}")
        return {}


def get_signal_stats(days: int = 30) -> dict[str, Any]:
    """Get behavioral signal statistics for the last N days."""
    conn = get_duckdb_connection()
    if conn is None:
        return {}

    try:
        result = conn.execute("""
            SELECT
                signal_type,
                COUNT(*) as count,
                AVG(signal_value) as avg_value
            FROM behavioral_signals
            WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL ? DAY
            GROUP BY signal_type
        """, [days])

        by_type = {row[0]: {"count": row[1], "avg_value": row[2]} for row in result.fetchall()}

        return {
            "by_type": by_type,
            "days": days,
        }
    except Exception as e:
        logger.error(f"Failed to get signal stats: {e}")
        return {}


def close_duckdb():
    """Close DuckDB connection."""
    global _duckdb_conn
    if _duckdb_conn is not None:
        _duckdb_conn.close()
        _duckdb_conn = None
        logger.info("DuckDB connection closed")
