"""Database module for knowledge base.

ARCHITECTURE NOTE:
- Graphiti/Neo4j is the SOURCE OF TRUTH for knowledge data
- SQLite stores page sync metadata, user feedback, and behavioral signals
"""

from knowledge_base.db.database import async_session_maker, engine, init_db
from knowledge_base.db.models import Base, RawPage

__all__ = [
    "Base",
    "RawPage",
    "engine",
    "async_session_maker",
    "init_db",
]
