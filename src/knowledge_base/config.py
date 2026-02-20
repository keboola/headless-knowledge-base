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
    LLM_PROVIDER: str = "claude"  # 'ollama', 'claude', or empty for auto-select

    # Ollama (local LLM)
    OLLAMA_BASE_URL: str = "http://ollama:11434"
    OLLAMA_LLM_MODEL: str = "llama3.1:8b"
    OLLAMA_EMBEDDING_MODEL: str = "mxbai-embed-large"

    # Embeddings
    EMBEDDING_PROVIDER: str = "sentence-transformer"  # 'sentence-transformer' or 'ollama'
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"  # sentence-transformer model
    INDEX_BATCH_SIZE: int = 100

    # Anthropic (Claude)
    ANTHROPIC_API_KEY: str = ""
    # Using Sonnet for Graphiti entity extraction - Haiku doesn't support the max_tokens
    # that graphiti-core internally uses (16384). Sonnet is more expensive but works.
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
    SEARCH_TOP_K: int = 10  # Default number of results (still used)

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
    # Gemini 2.5 Flash supports up to 65K output tokens (required for graphiti-core's 16384)
    # Gemini 2.0 Flash only supports 8K output which causes errors with graphiti
    VERTEX_AI_LLM_MODEL: str = "gemini-2.5-flash"  # Gemini model for entity extraction
    VERTEX_AI_CLAUDE_MODEL: str = "claude-sonnet-4@20250514"  # Claude via Vertex AI
    VERTEX_AI_BATCH_SIZE: int = 20  # Max texts per embedding batch (keep under 20k token limit)
    VERTEX_AI_TIMEOUT: float = 60.0  # API timeout in seconds

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
    def check_security_settings(self) -> "Settings":
        """Validate security settings."""
        if not self.DEBUG and self.ADMIN_PASSWORD == "changeme":
            logging.warning(
                "SECURITY WARNING: ADMIN_PASSWORD is set to default 'changeme' in non-debug mode!"
            )
        return self


settings = Settings()
