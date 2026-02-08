"""Database module for knowledge base.

ARCHITECTURE NOTE:
- Graphiti/Neo4j is the SOURCE OF TRUTH for knowledge data
- SQLite stores local models (RawPage, GovernanceMetadata, feedback, etc.)
"""

from knowledge_base.db.database import async_session_maker, engine, init_db
# NOTE: GovernanceMetadata is DEPRECATED - data now in Graphiti
from knowledge_base.db.models import Base, GovernanceMetadata, RawPage

__all__ = [
    "Base",
    "RawPage",
    "GovernanceMetadata",
    "engine",
    "async_session_maker",
    "init_db",
]
