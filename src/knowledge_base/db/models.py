"""SQLAlchemy models for the knowledge base.

ARCHITECTURE NOTE (per docs/ARCHITECTURE.md):
- ChromaDB is the SOURCE OF TRUTH for knowledge data (chunks, metadata, quality scores)
- SQLite/DuckDB stores ONLY analytics and feedback data

DEPRECATED MODELS (data now in ChromaDB):
- Chunk, ChunkMetadata, ChunkQuality, GovernanceMetadata
- These are kept for backward compatibility during migration but should not be used

ACTIVE MODELS (analytics/workflow):
- UserFeedback, BehavioralSignal, BotResponse, ChunkAccessLog
- Document, DocumentVersion, AreaApprover
- UserConfluenceLink, QueryRecord, EvalResult, QualityReport
- RawPage (kept for Confluence sync tracking)
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


# =============================================================================
# DEPRECATED MODELS - Data now stored in ChromaDB
# These models are kept for backward compatibility during migration.
# Do not use these for new code - use ChromaDB directly via vectorstore.client
# =============================================================================


class RawPage(Base):
    """Page metadata with reference to .md file on disk."""

    __tablename__ = "raw_pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    page_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    space_key: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(512))
    file_path: Mapped[str] = mapped_column(String(512))  # Path to .md file (random name)
    author: Mapped[str] = mapped_column(String(256))  # Account ID
    author_name: Mapped[str] = mapped_column(String(256), default="")  # Display name
    url: Mapped[str] = mapped_column(String(1024))
    parent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    downloaded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Version tracking
    version_number: Mapped[int] = mapped_column(Integer, default=1)

    # JSON fields stored as text
    permissions: Mapped[str] = mapped_column(Text, default="[]")
    labels: Mapped[str] = mapped_column(Text, default="[]")
    attachments: Mapped[str] = mapped_column(Text, default="[]")
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Status tracking
    status: Mapped[str] = mapped_column(String(32), default="active")

    # Staleness detection
    is_potentially_stale: Mapped[bool] = mapped_column(Boolean, default=False)
    staleness_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # Relationships
    governance: Mapped["GovernanceMetadata | None"] = relationship(
        "GovernanceMetadata", back_populates="page", uselist=False, cascade="all, delete-orphan"
    )
    chunks: Mapped[list["Chunk"]] = relationship(
        "Chunk", back_populates="page", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<RawPage(page_id={self.page_id}, title={self.title[:30]}...)>"


class GovernanceMetadata(Base):
    """DEPRECATED: Governance metadata extracted from Confluence labels.

    NOTE: Governance data (owner, classification, etc.) is now stored in ChromaDB metadata.
    See docs/adr/0005-chromadb-source-of-truth.md
    """

    __tablename__ = "governance_metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    page_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("raw_pages.page_id"), unique=True, index=True
    )

    # Governance fields (extracted from labels)
    owner: Mapped[str | None] = mapped_column(String(256), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    classification: Mapped[str] = mapped_column(String(32), default="internal")
    doc_type: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Relationships
    page: Mapped["RawPage"] = relationship("RawPage", back_populates="governance")

    def __repr__(self) -> str:
        return f"<GovernanceMetadata(page_id={self.page_id}, owner={self.owner})>"


class Chunk(Base):
    """DEPRECATED: Parsed content chunk from a Confluence page.

    NOTE: Chunk data is now stored directly in ChromaDB (source of truth).
    Use vectorstore.indexer.ChunkData and index_chunks_direct() for new code.
    See docs/adr/0005-chromadb-source-of-truth.md
    """

    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chunk_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    page_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("raw_pages.page_id"), index=True
    )

    # Content
    content: Mapped[str] = mapped_column(Text)
    chunk_type: Mapped[str] = mapped_column(String(32), default="text")  # text, code, table, list
    chunk_index: Mapped[int] = mapped_column(Integer)  # Order within page
    char_count: Mapped[int] = mapped_column(Integer)

    # Context
    parent_headers: Mapped[str] = mapped_column(Text, default="[]")  # JSON array of headers
    page_title: Mapped[str] = mapped_column(String(512))  # Denormalized for search context

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    page: Mapped["RawPage"] = relationship("RawPage", back_populates="chunks")
    chunk_metadata: Mapped["ChunkMetadata | None"] = relationship(
        "ChunkMetadata", back_populates="chunk", uselist=False, cascade="all, delete-orphan"
    )
    quality: Mapped["ChunkQuality | None"] = relationship(
        "ChunkQuality", back_populates="chunk", uselist=False, cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Chunk(chunk_id={self.chunk_id}, type={self.chunk_type}, chars={self.char_count})>"


class ChunkMetadata(Base):
    """DEPRECATED: AI-generated metadata for a chunk.

    NOTE: Metadata (topics, doc_type, summary, etc.) is now stored in ChromaDB metadata.
    See docs/adr/0005-chromadb-source-of-truth.md
    """

    __tablename__ = "chunk_metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chunk_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("chunks.chunk_id"), unique=True, index=True
    )

    # AI-generated fields
    topics: Mapped[str] = mapped_column(Text, default="[]")  # JSON: ["onboarding", "benefits"]
    intents: Mapped[str] = mapped_column(Text, default="[]")  # JSON: ["new_employee", "planning_vacation"]
    audience: Mapped[str] = mapped_column(Text, default="[]")  # JSON: ["all_employees", "engineering"]
    doc_type: Mapped[str] = mapped_column(String(32), default="general")  # policy, how-to, reference, FAQ
    key_entities: Mapped[str] = mapped_column(Text, default="[]")  # JSON: ["GCP", "Snowflake", "Prague"]
    summary: Mapped[str] = mapped_column(Text, default="")  # 1-2 sentence summary
    complexity: Mapped[str] = mapped_column(String(16), default="intermediate")  # beginner, intermediate, advanced

    # Timestamps
    generated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    chunk: Mapped["Chunk"] = relationship("Chunk", back_populates="chunk_metadata")

    def __repr__(self) -> str:
        return f"<ChunkMetadata(chunk_id={self.chunk_id}, doc_type={self.doc_type})>"


def calculate_staleness(updated_at: datetime) -> tuple[bool, str | None]:
    """
    Calculate if a document is potentially stale.

    Documents not updated in 2+ years are flagged as potentially stale.
    """
    # Handle timezone-aware and naive datetimes
    now = datetime.utcnow()
    if updated_at.tzinfo is not None:
        # Make now timezone-aware for comparison
        from datetime import timezone
        now = datetime.now(timezone.utc)

    age_days = (now - updated_at).days
    if age_days > 730:  # 2 years
        return True, f"Not updated in {age_days} days"
    return False, None


# =============================================================================
# Knowledge Lifecycle Management Models
# NOTE: ChunkQuality is DEPRECATED - quality data now in ChromaDB
# =============================================================================


# =============================================================================
# Indexing Checkpoint System (Phase 13.5)
# =============================================================================


class IndexingCheckpoint(Base):
    """Track indexing progress for resume capability.

    Enables resumable indexing so timeouts don't lose progress.
    Tracks which chunks have been indexed with status (pending/indexed/failed/skipped).
    """

    __tablename__ = "indexing_checkpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chunk_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    # Statuses: pending, indexed, failed, skipped

    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    page_id: Mapped[str] = mapped_column(String(64), index=True)

    def __repr__(self) -> str:
        return f"<IndexingCheckpoint(chunk_id={self.chunk_id}, status={self.status})>"


class ChunkQuality(Base):
    """DEPRECATED: Quality tracking for chunks with usage-based decay.

    NOTE: Quality scores (quality_score, access_count, feedback_count) are now stored
    in ChromaDB metadata (source of truth). Use vectorstore.client methods:
    - update_quality_score() - Update quality score
    - get_quality_score() - Read current score
    - update_single_metadata() - Update access_count, feedback_count
    See docs/adr/0005-chromadb-source-of-truth.md
    """

    __tablename__ = "chunk_quality"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chunk_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("chunks.chunk_id"), unique=True, index=True
    )

    # Scoring
    quality_score: Mapped[float] = mapped_column(Float, default=100.0)
    base_score: Mapped[float] = mapped_column(Float, default=100.0)

    # Usage tracking (for decay calculation)
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    access_count_30d: Mapped[int] = mapped_column(Integer, default=0)

    # Decay tracking
    last_decay_calculation: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    current_decay_rate: Mapped[float] = mapped_column(Float, default=2.0)

    # Status: active, deprecated, cold_storage, hard_archived
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    deprecated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cold_archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    hard_archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deprecation_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Relationships
    chunk: Mapped["Chunk"] = relationship("Chunk", back_populates="quality")

    def __repr__(self) -> str:
        return f"<ChunkQuality(chunk_id={self.chunk_id}, score={self.quality_score}, status={self.status})>"


class ChunkAccessLog(Base):
    """Track individual chunk accesses for usage-based decay."""

    __tablename__ = "chunk_access_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chunk_id: Mapped[str] = mapped_column(String(128), index=True)
    slack_user_id: Mapped[str] = mapped_column(String(64), index=True)
    accessed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    query_context: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<ChunkAccessLog(chunk_id={self.chunk_id}, user={self.slack_user_id})>"


class UserFeedback(Base):
    """User feedback on content chunks (Slack-authenticated)."""

    __tablename__ = "user_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chunk_id: Mapped[str] = mapped_column(String(128), index=True)

    # Slack user info (authenticated)
    slack_user_id: Mapped[str] = mapped_column(String(64), index=True)
    slack_username: Mapped[str] = mapped_column(String(256))
    slack_channel_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Feedback type: helpful, outdated, incorrect, confusing
    feedback_type: Mapped[str] = mapped_column(String(32), index=True)

    # Optional details
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_correction: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Context
    query_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    conversation_thread_ts: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Admin review
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    review_action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<UserFeedback(chunk_id={self.chunk_id}, type={self.feedback_type}, user={self.slack_user_id})>"


class ContentConflict(Base):
    """Track conflicts between content chunks (AI-detected or user-reported)."""

    __tablename__ = "content_conflicts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Conflicting chunks
    chunk_a_id: Mapped[str] = mapped_column(String(128), index=True)
    chunk_b_id: Mapped[str] = mapped_column(String(128), index=True)

    # Conflict details
    conflict_type: Mapped[str] = mapped_column(String(32))  # contradiction, outdated_duplicate, ambiguous
    description: Mapped[str] = mapped_column(Text)
    detected_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    detected_by: Mapped[str] = mapped_column(String(32))  # user, ai

    # AI detection metadata
    similarity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Resolution
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)  # open, resolved, dismissed
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolution: Mapped[str | None] = mapped_column(String(32), nullable=True)  # keep_a, keep_b, merge, archive_both
    winner_chunk_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    def __repr__(self) -> str:
        return f"<ContentConflict(id={self.id}, type={self.conflict_type}, status={self.status})>"


class ArchivedChunk(Base):
    """Cold storage for archived chunks."""

    __tablename__ = "archived_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chunk_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    page_id: Mapped[str] = mapped_column(String(64), index=True)

    # Preserved content
    content: Mapped[str] = mapped_column(Text)
    chunk_type: Mapped[str] = mapped_column(String(32))
    chunk_index: Mapped[int] = mapped_column(Integer)
    parent_headers: Mapped[str] = mapped_column(Text, default="[]")
    page_title: Mapped[str] = mapped_column(String(512))

    # Archive metadata
    original_created_at: Mapped[datetime] = mapped_column(DateTime)
    cold_archived_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    archive_reason: Mapped[str] = mapped_column(String(512))
    final_quality_score: Mapped[float] = mapped_column(Float)

    # For potential restoration
    original_page_file_path: Mapped[str] = mapped_column(String(512))

    def __repr__(self) -> str:
        return f"<ArchivedChunk(chunk_id={self.chunk_id}, archived_at={self.cold_archived_at})>"


class ArchivedChunkQuality(Base):
    """Preserved quality data for archived chunks."""

    __tablename__ = "archived_chunk_quality"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chunk_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    final_quality_score: Mapped[float] = mapped_column(Float)
    total_access_count: Mapped[int] = mapped_column(Integer)
    total_feedback_count: Mapped[int] = mapped_column(Integer)
    cold_archived_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    def __repr__(self) -> str:
        return f"<ArchivedChunkQuality(chunk_id={self.chunk_id}, final_score={self.final_quality_score})>"


# =============================================================================
# Behavioral Signals (Phase 10.5)
# =============================================================================


class BehavioralSignal(Base):
    """Implicit behavioral signals from Slack interactions.

    Tracks: follow-ups, reactions, gratitude, frustration, timeouts.
    Used to enhance quality scoring without explicit feedback.
    """

    __tablename__ = "behavioral_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Link to the bot response that triggered this signal
    response_ts: Mapped[str] = mapped_column(String(64), index=True)  # Slack message ts
    thread_ts: Mapped[str] = mapped_column(String(64), index=True)  # Thread ts

    # Chunk(s) that were shown in the response
    chunk_ids: Mapped[str] = mapped_column(Text, default="[]")  # JSON array

    # User who generated the signal
    slack_user_id: Mapped[str] = mapped_column(String(64), index=True)

    # Signal details
    signal_type: Mapped[str] = mapped_column(String(32), index=True)
    # Types: follow_up, thanks, frustration, positive_reaction, negative_reaction, satisfied_silence
    signal_value: Mapped[float] = mapped_column(Float)  # Score impact (-1.0 to +1.0)

    # Context
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # Original message
    reaction: Mapped[str | None] = mapped_column(String(64), nullable=True)  # Emoji name

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    def __repr__(self) -> str:
        return f"<BehavioralSignal(type={self.signal_type}, value={self.signal_value}, user={self.slack_user_id})>"


class BotResponse(Base):
    """Track bot responses for behavioral signal correlation.

    Links response messages to the chunks that were used in the answer.
    """

    __tablename__ = "bot_responses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Slack message identifiers
    response_ts: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    thread_ts: Mapped[str] = mapped_column(String(64), index=True)
    channel_id: Mapped[str] = mapped_column(String(64), index=True)

    # User who asked the question
    user_id: Mapped[str] = mapped_column(String(64))

    # Question and response
    query: Mapped[str] = mapped_column(Text)
    response_text: Mapped[str] = mapped_column(Text)

    # Chunks used in response (JSON array of chunk_ids)
    chunk_ids: Mapped[str] = mapped_column(Text, default="[]")

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Tracking flags
    timeout_checked: Mapped[bool] = mapped_column(Boolean, default=False)
    has_follow_up: Mapped[bool] = mapped_column(Boolean, default=False)

    def __repr__(self) -> str:
        return f"<BotResponse(ts={self.response_ts}, chunks={len(self.chunk_ids)})>"


# =============================================================================
# Knowledge Graph Models (Phase 04.5)
# =============================================================================


class Entity(Base):
    """Extracted entities for knowledge graph.

    Entities include people, teams, products, locations, and topics
    extracted from documents for multi-hop reasoning.
    """

    __tablename__ = "entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(256), index=True)
    entity_type: Mapped[str] = mapped_column(String(32), index=True)
    # Types: person, team, product, location, topic

    # Alternative names for entity resolution
    aliases: Mapped[str] = mapped_column(Text, default="[]")  # JSON array

    # Metadata
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_count: Mapped[int] = mapped_column(Integer, default=1)  # How many docs mention this

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<Entity(id={self.entity_id}, name={self.name}, type={self.entity_type})>"


class Relationship(Base):
    """Relationships between entities and documents in the knowledge graph.

    Links documents to entities they mention, authors, and spaces.
    """

    __tablename__ = "relationships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Source can be a page_id or entity_id
    source_id: Mapped[str] = mapped_column(String(128), index=True)
    source_type: Mapped[str] = mapped_column(String(32))  # page, entity

    # Target is always an entity
    target_id: Mapped[str] = mapped_column(String(128), index=True)

    # Relationship type
    relation_type: Mapped[str] = mapped_column(String(64), index=True)
    # Types: mentions_person, mentions_team, mentions_product, mentions_location,
    #        authored_by, belongs_to_space, related_to_topic

    # Relationship strength (for ranking)
    weight: Mapped[float] = mapped_column(Float, default=1.0)

    # Context where relationship was found
    context: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    def __repr__(self) -> str:
        return f"<Relationship(source={self.source_id}, rel={self.relation_type}, target={self.target_id})>"


# =============================================================================
# User Authentication & Permissions (Phase 09)
# =============================================================================


class UserConfluenceLink(Base):
    """Link between Slack users and their Confluence accounts.

    Stores OAuth tokens for permission checking.
    """

    __tablename__ = "user_confluence_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Slack user info
    slack_user_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    slack_username: Mapped[str] = mapped_column(String(256), default="")

    # Confluence account info
    confluence_account_id: Mapped[str] = mapped_column(String(128), index=True)
    confluence_email: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # OAuth tokens (encrypted)
    access_token: Mapped[str] = mapped_column(Text)  # Encrypted
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)  # Encrypted
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Timestamps
    linked_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_used_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_refresh_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    def __repr__(self) -> str:
        return f"<UserConfluenceLink(slack={self.slack_user_id}, confluence={self.confluence_account_id})>"


# =============================================================================
# Nightly Evaluation Models (Phase 11.5)
# =============================================================================


class QueryRecord(Base):
    """Record of queries for evaluation sampling."""

    __tablename__ = "query_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    query_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    # Query details
    query: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)

    # Retrieved documents (JSON array of chunk_ids)
    retrieved_chunks: Mapped[str] = mapped_column(Text, default="[]")
    retrieved_docs_content: Mapped[str] = mapped_column(Text, default="[]")  # JSON: doc contents

    # User and context
    slack_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    channel_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    # Evaluation status
    evaluated: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    def __repr__(self) -> str:
        return f"<QueryRecord(id={self.query_id}, evaluated={self.evaluated})>"


class EvalResult(Base):
    """LLM-as-Judge evaluation results for quality monitoring."""

    __tablename__ = "eval_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    query_id: Mapped[str] = mapped_column(String(64), index=True)

    # Evaluation metrics (0.0 to 1.0)
    groundedness: Mapped[float] = mapped_column(Float)  # Is answer supported by docs?
    relevance: Mapped[float] = mapped_column(Float)  # Are docs relevant to query?
    completeness: Mapped[float] = mapped_column(Float)  # Does answer fully address query?
    overall: Mapped[float] = mapped_column(Float)  # Average of above

    # Timestamps
    evaluated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Batch tracking
    eval_batch_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    def __repr__(self) -> str:
        return f"<EvalResult(query_id={self.query_id}, overall={self.overall:.2f})>"


class QualityReport(Base):
    """Daily quality report from nightly evaluation."""

    __tablename__ = "quality_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_date: Mapped[datetime] = mapped_column(DateTime, unique=True, index=True)

    # Sample info
    sample_size: Mapped[int] = mapped_column(Integer)
    total_queries: Mapped[int] = mapped_column(Integer)

    # Aggregate metrics
    avg_groundedness: Mapped[float] = mapped_column(Float)
    avg_relevance: Mapped[float] = mapped_column(Float)
    avg_completeness: Mapped[float] = mapped_column(Float)
    avg_overall: Mapped[float] = mapped_column(Float)

    # Thresholds
    below_threshold_count: Mapped[int] = mapped_column(Integer, default=0)

    # Status
    alert_sent: Mapped[bool] = mapped_column(Boolean, default=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    def __repr__(self) -> str:
        return f"<QualityReport(date={self.report_date}, overall={self.avg_overall:.2f})>"


# =============================================================================
# Governance Models (Phase 12)
# =============================================================================


class GovernanceIssue(Base):
    """Governance issues for tracking content problems."""

    __tablename__ = "governance_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # What the issue is about
    page_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    space_key: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

    # Issue details
    issue_type: Mapped[str] = mapped_column(String(32), index=True)
    # Types: obsolete, low_quality, gap, conflicting, stale
    description: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(16), default="medium")
    # Severities: low, medium, high, critical

    # Detection info
    detected_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    detection_method: Mapped[str] = mapped_column(String(32), default="automatic")
    # Methods: automatic, user_reported, llm_analysis

    # Resolution
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    # Statuses: open, in_progress, resolved, dismissed
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Assignment
    assigned_to: Mapped[str | None] = mapped_column(String(64), nullable=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<GovernanceIssue(type={self.issue_type}, severity={self.severity}, status={self.status})>"


class DocumentationGap(Base):
    """Identified documentation gaps from unanswered queries."""

    __tablename__ = "documentation_gaps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Gap info
    topic: Mapped[str] = mapped_column(String(256), index=True)
    suggested_title: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Query cluster info
    query_count: Mapped[int] = mapped_column(Integer)
    sample_queries: Mapped[str] = mapped_column(Text, default="[]")  # JSON array

    # Detection
    detected_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Resolution
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    resolved_page_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<DocumentationGap(topic={self.topic[:30]}..., queries={self.query_count})>"


# =============================================================================
# Document Creation Models (Phase 14)
# =============================================================================


class Document(Base):
    """User-created documents in the knowledge base."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    # Content
    title: Mapped[str] = mapped_column(String(512))
    content: Mapped[str] = mapped_column(Text)

    # Governance
    area: Mapped[str] = mapped_column(String(32), index=True)
    # Areas: people, finance, engineering, general, etc.
    doc_type: Mapped[str] = mapped_column(String(32), index=True)
    # Types: policy, procedure, guideline, information
    classification: Mapped[str] = mapped_column(String(32), default="internal")
    # Classifications: public, internal, confidential
    owner: Mapped[str | None] = mapped_column(String(64), nullable=True)  # Slack user ID

    # Lifecycle
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    # Statuses: draft, in_review, approved, published, rejected, archived
    version: Mapped[int] = mapped_column(Integer, default=1)

    # Creator info
    created_by: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Update tracking
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Approval info (JSON list of approvers stored as Text)
    pending_approvers: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    approved_by: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Rejection info
    rejected_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Source tracking
    source_type: Mapped[str] = mapped_column(String(32), default="manual")
    # Sources: manual, thread_summary, ai_draft
    source_thread_ts: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_channel_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Publishing
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    confluence_page_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Archive info
    archived_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    archive_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<Document(id={self.doc_id}, title={self.title[:30]}..., status={self.status})>"


class AreaApprover(Base):
    """Approvers for document areas."""

    __tablename__ = "area_approvers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    area: Mapped[str] = mapped_column(String(32), index=True)
    approver_slack_id: Mapped[str] = mapped_column(String(64), index=True)
    approver_name: Mapped[str] = mapped_column(String(256), default="")

    # Active status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Timestamps
    added_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    added_by: Mapped[str | None] = mapped_column(String(64), nullable=True)

    def __repr__(self) -> str:
        return f"<AreaApprover(area={self.area}, approver={self.approver_slack_id})>"


class DocumentVersion(Base):
    """Version history for documents."""

    __tablename__ = "document_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_id: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer)

    # Content snapshot
    title: Mapped[str] = mapped_column(String(512))
    content: Mapped[str] = mapped_column(Text)

    # Change tracking
    changed_by: Mapped[str] = mapped_column(String(64))
    changed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    change_summary: Mapped[str | None] = mapped_column(String(512), nullable=True)

    def __repr__(self) -> str:
        return f"<DocumentVersion(doc_id={self.doc_id}, version={self.version})>"
