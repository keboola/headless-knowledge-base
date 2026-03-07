"""Configuration management using pydantic-settings."""

import logging
import os

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    APP_NAME: str = "Knowledge Base"
    DEBUG: bool = False

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./knowledge_base.db"
    # Path to persist checkpoint DB (e.g. GCS FUSE mount). When set, the DB is
    # copied here after every checkpoint flush for crash-resilient resume.
    CHECKPOINT_PERSIST_PATH: str = ""

    # File Storage
    PAGES_DIR: str = "data/pages"  # Flat directory for .md files with random names

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"

    # LLM Provider Selection
    LLM_PROVIDER: str = "gemini"  # 'gemini', 'claude', 'vertex-claude', or 'ollama'

    # Ollama (local LLM)
    OLLAMA_BASE_URL: str = "http://ollama:11434"
    OLLAMA_LLM_MODEL: str = "llama3.1:8b"
    OLLAMA_EMBEDDING_MODEL: str = "mxbai-embed-large"

    # Embeddings
    EMBEDDING_PROVIDER: str = "sentence-transformer"  # 'sentence-transformer' or 'ollama'
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"  # sentence-transformer model
    INDEX_BATCH_SIZE: int = 100

    # Gemini model settings (separate models for different use cases)
    # Gemini 2.5 Flash supports up to 65K output tokens (required for graphiti-core's 16384)
    GEMINI_INTAKE_MODEL: str = "gemini-2.5-flash"  # Graphiti entity extraction (intake pipeline)
    GEMINI_CONVERSATION_MODEL: str = "gemini-2.5-flash"  # Slack bot RAG conversations

    # Anthropic (Claude) — used when LLM_PROVIDER=claude
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-sonnet-4-20250514"
    METADATA_BATCH_SIZE: int = 10

    # Confluence
    CONFLUENCE_URL: str = "https://your-domain.atlassian.net"
    CONFLUENCE_USERNAME: str = ""
    CONFLUENCE_API_TOKEN: str = ""
    CONFLUENCE_SPACE_KEYS: str = ""  # Comma-separated: "ENG,HR,DOCS"

    # Knowledge Lifecycle Management
    HARD_ARCHIVE_PATH: str = "data/archive"  # Directory for hard-archived JSON files
    COLD_ARCHIVE_DAYS: int = 90  # Days in cold storage before hard archive
    SCORE_THRESHOLD_DEPRECATED: int = 40  # Score below this = deprecated
    SCORE_THRESHOLD_ARCHIVE: int = 10  # Score below this = cold storage
    CONFLICT_SIMILARITY_THRESHOLD: float = 0.85  # Embedding similarity for conflict detection
    CONFLICT_CONFIDENCE_THRESHOLD: float = 0.7  # LLM confidence for flagging conflicts

    # Feedback Score Impact
    FEEDBACK_SCORE_HELPFUL: int = 2  # Points added for helpful feedback
    FEEDBACK_SCORE_OUTDATED: int = -15  # Points for outdated feedback
    FEEDBACK_SCORE_INCORRECT: int = -25  # Points for incorrect feedback
    FEEDBACK_SCORE_CONFUSING: int = -5  # Points for confusing feedback

    # Slack
    SLACK_BOT_TOKEN: str = ""  # xoxb-...
    SLACK_SIGNING_SECRET: str = ""
    SLACK_APP_TOKEN: str = ""  # xapp-... (for socket mode, optional)
    SLACK_COMMAND_PREFIX: str = ""  # "staging-" for staging app, "" for prod
    KNOWLEDGE_ADMIN_CHANNEL: str = "#knowledge-admins"  # Channel for admin escalations

    # Web UI Admin
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "changeme"  # MUST be changed in production

    # Search
    SEARCH_TOP_K: int = 10  # Default number of results (legacy, used by HybridRetriever fallback)
    SEARCH_DEFAULT_LIMIT: int = 20  # Default search result limit for Q&A pipeline
    SEARCH_CHUNK_CONTENT_LIMIT: int = 4000  # Max chars per chunk in LLM context
    SEARCH_QUERY_EXPANSION_ENABLED: bool = True  # Enable LLM-based query expansion
    SEARCH_QUERY_EXPANSION_MAX_VARIANTS: int = 3  # Max query variants including original
    SEARCH_MIN_CONTENT_LENGTH: int = 20  # Min chars for a result to be considered meaningful

    # Knowledge Governance (Phase 15)
    GOVERNANCE_ENABLED: bool = False  # Feature flag for gradual rollout
    GOVERNANCE_LOW_RISK_THRESHOLD: int = 35  # Score 0-35 = auto-approve
    GOVERNANCE_HIGH_RISK_THRESHOLD: int = 66  # Score 66-100 = require approval
    GOVERNANCE_TRUSTED_DOMAINS: str = "keboola.com"  # Comma-separated trusted email domains
    GOVERNANCE_REVERT_WINDOW_HOURS: int = 24  # Hours for medium-risk revert window
    GOVERNANCE_AUTO_REJECT_DAYS: int = 14  # Days before pending items auto-rejected
    GOVERNANCE_CONTRADICTION_CHECK_ENABLED: bool = True  # LLM contradiction detection
    GOVERNANCE_NOVELTY_SIMILARITY_THRESHOLD: float = 0.7  # Cosine sim for "existing topic"

    # Graph Database (Graphiti + Neo4j)
    GRAPH_BACKEND: str = "neo4j"  # "neo4j" for all environments
    GRAPH_KUZU_PATH: str = "data/kuzu_graph"  # DEPRECATED: Kuzu no longer used
    GRAPH_GROUP_ID: str = "default"  # Graphiti group ID for multi-tenancy
    # Neo4j settings (for production)
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = ""
    # Neo4j connection pool resilience (seconds)
    NEO4J_LIVENESS_CHECK_TIMEOUT: int = 30  # Check connection health before use
    NEO4J_MAX_CONNECTION_LIFETIME: int = 1800  # Recycle connections every 30 min
    NEO4J_CONNECTION_ACQUISITION_TIMEOUT: int = 60  # Wait up to 60s for a connection
    # Neo4j search retry on connection error (RuntimeError: TCPTransport closed)
    NEO4J_SEARCH_MAX_RETRIES: int = 1  # Retries on stale connection in search path
    # Feature flags for Graphiti-only architecture
    GRAPH_ENABLE_GRAPHITI: bool = True  # Master switch for Graphiti (now required)
    GRAPH_EXPANSION_ENABLED: bool = True  # Always enabled with Graphiti-only

    # GCP Deployment Settings
    GCP_PROJECT_ID: str = ""  # GCP project ID (e.g., ai-knowledge-base-42)
    GCP_REGION: str = "us-central1"  # GCP region for services

    # Vertex AI Settings
    VERTEX_AI_PROJECT: str = ""  # Falls back to GCP_PROJECT_ID if empty
    VERTEX_AI_LOCATION: str = "us-central1"  # Region for Vertex AI
    VERTEX_AI_EMBEDDING_MODEL: str = "text-embedding-005"  # Embedding model
    VERTEX_AI_EMBEDDING_DIMENSION: int = 768  # Embedding dimension
    # DEPRECATED: Use GEMINI_INTAKE_MODEL / GEMINI_CONVERSATION_MODEL instead.
    # Kept for backward compat with existing deployments that set this env var.
    VERTEX_AI_LLM_MODEL: str = ""
    VERTEX_AI_CLAUDE_MODEL: str = "claude-sonnet-4@20250514"  # Claude via Vertex AI
    VERTEX_AI_BATCH_SIZE: int = 20  # Max texts per embedding batch (keep under 20k token limit)
    VERTEX_AI_TIMEOUT: float = 60.0  # API timeout in seconds

    # Keboola Storage API
    KEBOOLA_API_TOKEN: str = ""
    KEBOOLA_API_URL: str = ""  # e.g. https://connection.us-east4.gcp.keboola.com
    KEBOOLA_TABLE_ID: str = ""  # e.g. in.c-bucket.table-name
    KEBOOLA_SOURCE_KEY: str = "KEBOOLA"  # space_key for Keboola-sourced chunks

    # Graphiti Indexing Performance
    GRAPHITI_CONCURRENCY: int = 5  # Concurrent chunks (1=sequential, 5-10=parallel)
    GRAPHITI_INTER_CHUNK_DELAY: float = 0.0  # Delay between chunks (0.0 with semaphore)
    GRAPHITI_RATE_LIMIT_THRESHOLD: int = 5  # Circuit breaker threshold
    GRAPHITI_CIRCUIT_BREAKER_COOLDOWN: int = 60  # Cooldown seconds
    GRAPHITI_MAX_CONCURRENCY: int = 10  # Safety limit

    # Graphiti Bulk Indexing (adaptive batch sizing)
    GRAPHITI_BULK_ENABLED: bool = True  # Use add_episode_bulk() with adaptive batching
    GRAPHITI_BULK_INITIAL_BATCH: int = 2  # Starting batch size (doubles in slow_start)
    GRAPHITI_BULK_MAX_BATCH: int = 20  # Maximum batch size cap

    # Batch Import Pipeline (Gemini Batch API + direct Neo4j import)
    BATCH_GCS_BUCKET: str = ""  # GCS bucket for batch JSONL files
    BATCH_GCS_PREFIX: str = "batch-import"  # Path prefix within bucket
    BATCH_GEMINI_MODEL: str = "gemini-2.5-flash"  # Model for batch extraction
    BATCH_ENTITY_SIMILARITY_THRESHOLD: float = 0.85  # Cosine similarity for entity dedup
    BATCH_NEO4J_WRITE_SIZE: int = 500  # Rows per UNWIND batch for Neo4j bulk writes
    BATCH_EMBEDDING_CONCURRENCY: int = 3  # Max parallel embedding batches (keep low to avoid 429)
    BATCH_POLL_INTERVAL: int = 60  # Seconds between batch job polls
    BATCH_MAX_POLL_DURATION: int = 21600  # Max wait for batch job (6 hours)

    @property
    def governance_trusted_domain_list(self) -> list[str]:
        """Get governance trusted domains as a list."""
        return [d.strip() for d in self.GOVERNANCE_TRUSTED_DOMAINS.split(",") if d.strip()]

    @property
    def is_gcp_deployment(self) -> bool:
        """Check if running in GCP environment."""
        return bool(os.environ.get("K_SERVICE") or self.GCP_PROJECT_ID)

    @property
    def confluence_space_list(self) -> list[str]:
        """Get Confluence space keys as a list."""
        if not self.CONFLUENCE_SPACE_KEYS:
            return []
        return [s.strip() for s in self.CONFLUENCE_SPACE_KEYS.split(",") if s.strip()]

    @model_validator(mode="after")
    def migrate_vertex_ai_llm_model(self) -> "Settings":
        """Backward compat: map deprecated VERTEX_AI_LLM_MODEL to new settings."""
        if self.VERTEX_AI_LLM_MODEL:
            if not os.environ.get("GEMINI_INTAKE_MODEL"):
                self.GEMINI_INTAKE_MODEL = self.VERTEX_AI_LLM_MODEL
            if not os.environ.get("GEMINI_CONVERSATION_MODEL"):
                self.GEMINI_CONVERSATION_MODEL = self.VERTEX_AI_LLM_MODEL
        return self

    @model_validator(mode="after")
    def check_security_settings(self) -> "Settings":
        """Validate security settings."""
        if not self.DEBUG and self.ADMIN_PASSWORD == "changeme":
            logging.warning(
                "SECURITY WARNING: ADMIN_PASSWORD is set to default 'changeme' in non-debug mode!"
            )
        return self


settings = Settings()
