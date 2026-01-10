"""Database connection and session management.

ARCHITECTURE NOTE (per docs/ARCHITECTURE.md):
- ChromaDB is the SOURCE OF TRUTH for knowledge data
- SQLite stores legacy models (being phased out)
- DuckDB stores analytics data (UserFeedback, BehavioralSignal, etc.)
"""

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from knowledge_base.config import settings


def _set_sqlite_pragma(dbapi_conn, connection_record):
    """Set SQLite pragmas for better concurrency.

    WAL mode allows concurrent reads during writes, solving the
    database locking issue during long-running operations like parsing.
    """
    cursor = dbapi_conn.cursor()
    # WAL mode: allows readers while writing
    cursor.execute("PRAGMA journal_mode=WAL")
    # 30 second timeout for busy connections
    cursor.execute("PRAGMA busy_timeout=30000")
    # Synchronous=NORMAL is safe with WAL and faster
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


# Create async engine
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
)

# Enable WAL mode for SQLite (allows concurrent reads during writes)
if settings.DATABASE_URL.startswith("sqlite"):
    event.listen(engine.sync_engine, "connect", _set_sqlite_pragma)

# Create session factory
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    """Initialize database and create all tables.

    Initializes both SQLite (for legacy models) and DuckDB (for analytics).
    """
    from knowledge_base.db.models import Base

    # Initialize SQLite tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Initialize DuckDB tables for analytics
    try:
        from knowledge_base.db.duckdb_schema import init_duckdb_schema
        init_duckdb_schema()
    except ImportError:
        # DuckDB not installed - analytics will be unavailable
        pass


async def get_session() -> AsyncSession:
    """Get a database session."""
    async with async_session_maker() as session:
        yield session
