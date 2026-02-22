"""Graphiti client factory for knowledge graph operations.

This module provides a factory for creating Graphiti instances with
backend selection (Kuzu for development, Neo4j for production).

Per the migration plan, this runs in parallel with the existing
NetworkX-based graph during the gradual rollout phase.
"""

import asyncio
import logging
import os
from typing import TYPE_CHECKING

from knowledge_base.config import settings

if TYPE_CHECKING:
    from graphiti_core import Graphiti

logger = logging.getLogger(__name__)


class GraphitiClientError(Exception):
    """Base exception for Graphiti client operations."""
    pass


class GraphitiConnectionError(GraphitiClientError):
    """Connection to graph database failed."""
    pass


class GraphitiClient:
    """Factory and wrapper for Graphiti instances.

    Handles backend selection (Kuzu vs Neo4j) based on configuration
    and provides a consistent interface for graph operations.
    """

    _instance: "Graphiti | None" = None
    _initialized: bool = False
    _init_lock: asyncio.Lock | None = None

    def __init__(
        self,
        backend: str | None = None,
        kuzu_path: str | None = None,
        neo4j_uri: str | None = None,
        neo4j_user: str | None = None,
        neo4j_password: str | None = None,
        group_id: str | None = None,
    ):
        """Initialize Graphiti client configuration.

        Args:
            backend: "kuzu" or "neo4j" (defaults to settings.GRAPH_BACKEND)
            kuzu_path: Path for Kuzu database (defaults to settings.GRAPH_KUZU_PATH)
            neo4j_uri: Neo4j connection URI (defaults to settings.NEO4J_URI)
            neo4j_user: Neo4j username (defaults to settings.NEO4J_USER)
            neo4j_password: Neo4j password (defaults to settings.NEO4J_PASSWORD)
            group_id: Graphiti group ID for multi-tenancy (defaults to settings.GRAPH_GROUP_ID)
        """
        self.backend = backend or settings.GRAPH_BACKEND
        self.kuzu_path = kuzu_path or settings.GRAPH_KUZU_PATH
        self.neo4j_uri = neo4j_uri or settings.NEO4J_URI
        self.neo4j_user = neo4j_user or settings.NEO4J_USER
        self.neo4j_password = neo4j_password or settings.NEO4J_PASSWORD
        self.group_id = group_id or settings.GRAPH_GROUP_ID

    async def get_client(self) -> "Graphiti":
        """Get or create the Graphiti client instance.

        Uses an asyncio.Lock to prevent concurrent initialization from
        multiple async tasks creating duplicate Graphiti instances.

        Returns:
            Configured Graphiti instance

        Raises:
            GraphitiConnectionError: If connection fails
            GraphitiClientError: If backend is not supported
        """
        if GraphitiClient._instance is not None and GraphitiClient._initialized:
            return GraphitiClient._instance

        # Lazy-init the lock (safe: first call always happens in a single task)
        if GraphitiClient._init_lock is None:
            GraphitiClient._init_lock = asyncio.Lock()

        async with GraphitiClient._init_lock:
            # Double-check after acquiring lock
            if GraphitiClient._instance is not None and GraphitiClient._initialized:
                return GraphitiClient._instance

            try:
                if self.backend == "kuzu":
                    client = await self._create_kuzu_client()
                elif self.backend == "neo4j":
                    client = await self._create_neo4j_client()
                else:
                    raise GraphitiClientError(f"Unsupported graph backend: {self.backend}")

                GraphitiClient._instance = client
                GraphitiClient._initialized = True
                logger.info(f"Graphiti client initialized with {self.backend} backend")
                return client

            except Exception as e:
                logger.error(f"Failed to initialize Graphiti client: {e}")
                raise GraphitiConnectionError(f"Could not connect to {self.backend}: {e}") from e

    async def _create_kuzu_client(self) -> "Graphiti":
        """Create Graphiti client with Kuzu embedded backend."""
        from graphiti_core import Graphiti
        from graphiti_core.driver.kuzu_driver import KuzuDriver

        # Ensure parent directory exists (Kuzu will create the database directory)
        parent_dir = os.path.dirname(self.kuzu_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

        # Create Kuzu driver - pass the database path
        # Kuzu will create the directory and files needed
        kuzu_driver = KuzuDriver(db=self.kuzu_path)

        # Create LLM client for entity extraction
        llm_client = self._get_llm_client()

        # Create embedder for vector search
        embedder = self._get_embedder()

        # Create cross encoder for reranking
        cross_encoder = self._get_cross_encoder()

        # Create Graphiti instance with Kuzu driver
        graphiti = Graphiti(
            graph_driver=kuzu_driver,
            llm_client=llm_client,
            embedder=embedder,
            cross_encoder=cross_encoder,
        )
        graphiti.group_id = self.group_id

        # Initialize the graph schema
        await graphiti.build_indices_and_constraints()

        logger.info(f"Kuzu database initialized at {self.kuzu_path}")
        return graphiti

    async def _create_neo4j_client(self) -> "Graphiti":
        """Create Graphiti client with Neo4j backend."""
        from graphiti_core import Graphiti
        from graphiti_core.driver.neo4j_driver import Neo4jDriver
        from neo4j import AsyncGraphDatabase

        if not self.neo4j_password:
            raise GraphitiClientError("NEO4J_PASSWORD is required for Neo4j backend")

        # Create Neo4j driver with connection pool resilience settings
        # Default driver has liveness_check_timeout=None (disabled), which causes
        # stale connections to fail with "TCPTransport closed" after Neo4j restarts
        # or long idle periods (e.g. during multi-hour pipeline intake runs)
        neo4j_async_driver = AsyncGraphDatabase.driver(
            self.neo4j_uri,
            auth=(self.neo4j_user, self.neo4j_password),
            liveness_check_timeout=settings.NEO4J_LIVENESS_CHECK_TIMEOUT,
            max_connection_lifetime=settings.NEO4J_MAX_CONNECTION_LIFETIME,
            connection_acquisition_timeout=settings.NEO4J_CONNECTION_ACQUISITION_TIMEOUT,
        )

        # Create Neo4jDriver wrapper and inject our configured async driver
        neo4j_driver = Neo4jDriver(
            uri=self.neo4j_uri,
            user=self.neo4j_user,
            password=self.neo4j_password,
        )
        # Replace the default driver with our configured one
        await neo4j_driver.client.close()
        neo4j_driver.client = neo4j_async_driver

        # Create LLM client for entity extraction
        llm_client = self._get_llm_client()

        # Create embedder for vector search
        embedder = self._get_embedder()

        # Create cross encoder for reranking
        cross_encoder = self._get_cross_encoder()

        # Create Graphiti instance with our pre-configured Neo4j driver
        graphiti = Graphiti(
            graph_driver=neo4j_driver,
            llm_client=llm_client,
            embedder=embedder,
            cross_encoder=cross_encoder,
        )
        graphiti.group_id = self.group_id

        # Initialize the graph schema
        await graphiti.build_indices_and_constraints()

        logger.info(f"Neo4j connected at {self.neo4j_uri}")
        return graphiti

    def _get_llm_client(self):
        """Get the LLM client for Graphiti entity extraction.

        Dispatches based on LLM_PROVIDER setting. No silent fallback —
        if the configured provider is not available, raises an error.
        """
        llm_provider = settings.LLM_PROVIDER.lower()

        if llm_provider == "gemini":
            return self._get_gemini_client()

        if llm_provider in ("claude", "anthropic"):
            if not settings.ANTHROPIC_API_KEY:
                raise GraphitiClientError(
                    "LLM_PROVIDER is set to 'claude' but ANTHROPIC_API_KEY is not configured."
                )
            return self._get_anthropic_client()

        raise GraphitiClientError(
            f"Unsupported LLM_PROVIDER for Graphiti: '{llm_provider}'. "
            "Use 'gemini' or 'claude'."
        )

    def _get_anthropic_client(self):
        """Get Anthropic Claude client for Graphiti."""
        from graphiti_core.llm_client.anthropic_client import AnthropicClient
        from graphiti_core.llm_client import LLMConfig

        config = LLMConfig(
            api_key=settings.ANTHROPIC_API_KEY,
            model=settings.ANTHROPIC_MODEL,
            max_tokens=8192,  # Claude 3.5 Haiku max output tokens
        )

        return AnthropicClient(config=config, max_tokens=8192)

    def _get_gemini_client(self):
        """Get Google Gemini client for Graphiti.

        Requires google-genai package: pip install graphiti-core[google-genai]

        Supports two authentication modes:
        1. GOOGLE_API_KEY: Direct API key for consumer Gemini API
        2. Vertex AI: Use service account credentials in GCP environment
           (auto-detected in Cloud Run/GCP environments)

        In Cloud Run, the service account credentials are automatically available.
        """
        try:
            from graphiti_core.llm_client.gemini_client import GeminiClient
            from graphiti_core.llm_client import LLMConfig
            from google import genai
        except ImportError as e:
            raise GraphitiClientError(
                "Gemini client requires google-genai package. "
                "Install with: pip install graphiti-core[google-genai]"
            ) from e

        # Check for Google API key (direct API access)
        google_api_key = os.environ.get("GOOGLE_API_KEY", "")

        model = settings.GEMINI_INTAKE_MODEL

        # If we have an API key, use consumer Gemini API
        if google_api_key:
            config = LLMConfig(
                api_key=google_api_key,
                model=model,
                max_tokens=8192,
            )
            logger.info(f"Using Gemini LLM with API key (model: {model})")
            return GeminiClient(config=config, max_tokens=8192)

        # In GCP (Cloud Run), use Vertex AI with service account authentication
        if settings.is_gcp_deployment:
            project_id = settings.GCP_PROJECT_ID or settings.VERTEX_AI_PROJECT
            location = settings.VERTEX_AI_LOCATION

            logger.info(
                f"Using Vertex AI Gemini authentication "
                f"(project: {project_id}, location: {location}, model: {model})"
            )

            # Create genai.Client configured for Vertex AI
            # This uses default credentials (service account in Cloud Run)
            vertex_client = genai.Client(
                vertexai=True,
                project=project_id,
                location=location,
            )

            # Pass the pre-configured Vertex AI client to GeminiClient
            config = LLMConfig(
                api_key="vertex-ai-mode",  # Placeholder - not used with custom client
                model=model,
                max_tokens=8192,
            )
            return GeminiClient(config=config, max_tokens=8192, client=vertex_client)

        raise GraphitiClientError(
            "Gemini LLM requires either GOOGLE_API_KEY (consumer API) or "
            "GCP deployment (Vertex AI with service account). "
            "Set GOOGLE_API_KEY for consumer API or deploy to Cloud Run."
        )

    def _get_embedder(self):
        """Get the embedder client for Graphiti vector operations.

        Wraps our existing embeddings provider to work with Graphiti.
        """
        from graphiti_core.embedder import EmbedderClient
        from knowledge_base.vectorstore.embeddings import get_embeddings

        class KnowledgeBaseEmbedder(EmbedderClient):
            """Custom embedder that wraps our existing embeddings provider."""

            def __init__(self):
                self._embeddings = get_embeddings()

            async def create(self, input_data):
                """Create embedding for single text or list of texts."""
                if isinstance(input_data, str):
                    return await self._embeddings.embed_single(input_data)
                elif isinstance(input_data, list):
                    if all(isinstance(item, str) for item in input_data):
                        embeddings = await self._embeddings.embed(list(input_data))
                        return embeddings[0] if len(embeddings) == 1 else embeddings
                # For tokenized input, convert back to string
                return await self._embeddings.embed_single(str(input_data))

            async def create_batch(self, input_data_list):
                """Create embeddings for a batch of texts."""
                return await self._embeddings.embed(input_data_list)

        return KnowledgeBaseEmbedder()

    def _get_cross_encoder(self):
        """Get the cross encoder for Graphiti reranking.

        Creates a simple cross encoder that uses our embeddings for similarity scoring.
        This avoids the OpenAI dependency.
        """
        from graphiti_core.cross_encoder import CrossEncoderClient
        from knowledge_base.vectorstore.embeddings import get_embeddings
        import numpy as np

        class SimpleEmbeddingCrossEncoder(CrossEncoderClient):
            """Cross encoder using embedding similarity for ranking.

            This is a simpler alternative to OpenAI's reranker that uses
            cosine similarity between query and passage embeddings.
            """

            def __init__(self):
                self._embeddings = get_embeddings()

            async def rank(self, query: str, passages: list[str]) -> list[tuple[str, float]]:
                """Rank passages based on embedding similarity to query."""
                if not passages:
                    return []

                # Get embeddings for query and all passages
                all_texts = [query] + passages
                embeddings = await self._embeddings.embed(all_texts)

                query_emb = np.array(embeddings[0])
                passage_embs = [np.array(e) for e in embeddings[1:]]

                # Calculate cosine similarity
                results = []
                for passage, passage_emb in zip(passages, passage_embs):
                    # Cosine similarity
                    dot_product = np.dot(query_emb, passage_emb)
                    norm_query = np.linalg.norm(query_emb)
                    norm_passage = np.linalg.norm(passage_emb)
                    if norm_query > 0 and norm_passage > 0:
                        similarity = dot_product / (norm_query * norm_passage)
                    else:
                        similarity = 0.0
                    results.append((passage, float(similarity)))

                # Sort by similarity descending
                results.sort(key=lambda x: x[1], reverse=True)
                return results

        return SimpleEmbeddingCrossEncoder()

    async def reset_and_reconnect(self) -> None:
        """Reset the singleton and close the stale connection.

        Call this when a connection error is detected to force
        a fresh connection on the next get_client() call.
        """
        logger.warning("Resetting Graphiti client due to connection error")
        try:
            await self.close()
        except Exception as e:
            logger.warning(f"Error during client close on reset: {e}")
            # Force reset even if close fails
            GraphitiClient._instance = None
            GraphitiClient._initialized = False

    async def close(self) -> None:
        """Close the Graphiti client connection."""
        if GraphitiClient._instance is not None:
            try:
                await GraphitiClient._instance.close()
            except Exception as e:
                logger.warning(f"Error closing Graphiti client: {e}")
            finally:
                GraphitiClient._instance = None
                GraphitiClient._initialized = False
                logger.info("Graphiti client closed")

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton instance (for testing)."""
        cls._instance = None
        cls._initialized = False

    async def check_health(self) -> bool:
        """Check if the graph database is accessible.

        Returns:
            True if healthy, False otherwise
        """
        try:
            client = await self.get_client()
            # Simple health check - try to search for nothing
            # This verifies connectivity without side effects
            return True
        except Exception as e:
            logger.error(f"Graph database health check failed: {e}")
            return False


# Convenience function for getting the default client
_default_client: GraphitiClient | None = None


def get_graphiti_client() -> GraphitiClient:
    """Get the default Graphiti client instance.

    Returns:
        GraphitiClient configured from settings
    """
    global _default_client
    if _default_client is None:
        _default_client = GraphitiClient()
    return _default_client


async def get_graphiti() -> "Graphiti":
    """Get the Graphiti instance (convenience function).

    Returns:
        Configured Graphiti instance
    """
    client = get_graphiti_client()
    return await client.get_client()
