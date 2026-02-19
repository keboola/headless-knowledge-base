"""Database connection and session management.

ARCHITECTURE NOTE (per docs/ARCHITECTURE.md):
- Graphiti/Neo4j is the SOURCE OF TRUTH for knowledge data
- SQLite stores local models (RawPage, feedback, behavioral signals, etc.)
"""

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

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


# Create async engine with NullPool for SQLite.
# NullPool closes connections immediately when sessions end, preventing
# idle pooled connections from holding SQLite WAL file locks.
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    poolclass=NullPool,
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
    """Initialize database and create all tables."""
    from knowledge_base.db.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    """Get a database session."""
    async with async_session_maker() as session:
        yield session
