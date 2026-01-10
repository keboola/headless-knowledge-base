"""ChromaDB client for vector storage and retrieval.

This is the SOURCE OF TRUTH for all knowledge data per docs/ARCHITECTURE.md.
"""

import logging
import time
from functools import wraps
from typing import Any, Callable, TypeVar

import chromadb
from chromadb.config import Settings as ChromaSettings

from knowledge_base.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")


def with_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exceptions: tuple = (Exception,),
) -> Callable:
    """Decorator for retrying operations with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay between retries (seconds)
        max_delay: Maximum delay between retries (seconds)
        exceptions: Tuple of exceptions to catch and retry
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        delay = min(base_delay * (2 ** attempt), max_delay)
                        logger.warning(
                            f"Attempt {attempt + 1}/{max_retries + 1} failed for {func.__name__}: {e}. "
                            f"Retrying in {delay:.1f}s..."
                        )
                        time.sleep(delay)
                    else:
                        logger.error(f"All {max_retries + 1} attempts failed for {func.__name__}: {e}")
            raise last_exception
        return wrapper
    return decorator


class ChromaDBError(Exception):
    """Base exception for ChromaDB operations."""
    pass


class ChromaDBConnectionError(ChromaDBError):
    """Connection to ChromaDB failed."""
    pass


class ChromaDBNotFoundError(ChromaDBError):
    """Requested document(s) not found in ChromaDB."""
    pass

# Default collection name
DEFAULT_COLLECTION = "confluence_documents"


class ChromaClient:
    """Client for ChromaDB vector database operations."""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        use_ssl: bool | None = None,
        token: str | None = None,
        collection_name: str = DEFAULT_COLLECTION,
    ):
        """Initialize ChromaDB client.

        Args:
            host: ChromaDB host (defaults to settings.CHROMA_HOST)
            port: ChromaDB port (defaults to settings.CHROMA_PORT)
            use_ssl: Use HTTPS (defaults to settings.CHROMA_USE_SSL)
            token: Authentication token (defaults to settings.CHROMA_TOKEN)
            collection_name: Name of the collection to use
        """
        self.host = host or settings.CHROMA_HOST
        self.port = port or settings.CHROMA_PORT
        self.use_ssl = use_ssl if use_ssl is not None else settings.CHROMA_USE_SSL
        self.token = token or settings.CHROMA_TOKEN
        self.collection_name = collection_name
        self._client: chromadb.HttpClient | None = None
        self._collection: chromadb.Collection | None = None

    def _get_client(self) -> chromadb.HttpClient:
        """Get or create the ChromaDB client."""
        if self._client is None:
            protocol = "https" if self.use_ssl else "http"
            logger.info(f"Connecting to ChromaDB at {protocol}://{self.host}:{self.port}")

            # Build client kwargs
            client_kwargs = {
                "host": self.host,
                "port": self.port,
                "ssl": self.use_ssl,
                "settings": ChromaSettings(anonymized_telemetry=False),
            }

            # Add authentication if token is configured
            if self.token:
                logger.info("Using token authentication for ChromaDB")
                client_kwargs["headers"] = {"Authorization": f"Bearer {self.token}"}

            self._client = chromadb.HttpClient(**client_kwargs)
        return self._client

    def _get_collection(self) -> chromadb.Collection:
        """Get or create the collection."""
        if self._collection is None:
            client = self._get_client()
            self._collection = client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info(f"Using collection: {self.collection_name}")
        return self._collection

    async def upsert(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict[str, Any]],
    ) -> None:
        """Insert or update documents in the collection.

        Args:
            ids: Document IDs
            embeddings: Embedding vectors
            documents: Document texts
            metadatas: Metadata dictionaries
        """
        collection = self._get_collection()
        collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )
        logger.debug(f"Upserted {len(ids)} documents")

    async def delete(self, ids: list[str]) -> None:
        """Delete documents by ID.

        Args:
            ids: Document IDs to delete
        """
        collection = self._get_collection()
        collection.delete(ids=ids)
        logger.debug(f"Deleted {len(ids)} documents")

    async def query(
        self,
        query_embedding: list[float],
        n_results: int = 10,
        where: dict[str, Any] | None = None,
        where_document: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Query the collection for similar documents.

        Args:
            query_embedding: Query embedding vector
            n_results: Number of results to return
            where: Metadata filter
            where_document: Document content filter

        Returns:
            Query results with ids, documents, metadatas, distances
        """
        collection = self._get_collection()
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where=where,
            where_document=where_document,
            include=["documents", "metadatas", "distances"],
        )
        return results

    async def count(self) -> int:
        """Get the number of documents in the collection.

        Returns:
            Document count
        """
        collection = self._get_collection()
        return collection.count()

    async def get(
        self,
        ids: list[str] | None = None,
        where: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Get documents by ID or filter.

        Args:
            ids: Document IDs to retrieve
            where: Metadata filter
            limit: Maximum number of results

        Returns:
            Documents with ids, documents, metadatas
        """
        collection = self._get_collection()
        return collection.get(
            ids=ids,
            where=where,
            limit=limit,
            include=["documents", "metadatas"],
        )

    @with_retry(max_retries=3, base_delay=0.5)
    async def update_metadata(
        self,
        ids: list[str],
        metadatas: list[dict[str, Any]],
    ) -> None:
        """Update metadata for existing documents (without re-embedding).

        Args:
            ids: Document IDs to update
            metadatas: New metadata dictionaries (will be merged with existing)
        """
        collection = self._get_collection()
        collection.update(
            ids=ids,
            metadatas=metadatas,
        )
        logger.debug(f"Updated metadata for {len(ids)} documents")

    @with_retry(max_retries=3, base_delay=0.5)
    async def update_single_metadata(
        self,
        chunk_id: str,
        metadata_updates: dict[str, Any],
    ) -> None:
        """Update metadata for a single chunk.

        This is optimized for frequent single-chunk updates (e.g., quality score changes).

        Args:
            chunk_id: The chunk ID to update
            metadata_updates: Dictionary of metadata fields to update
        """
        collection = self._get_collection()

        # Get existing metadata first
        existing = collection.get(ids=[chunk_id], include=["metadatas"])
        if not existing["ids"]:
            raise ChromaDBNotFoundError(f"Chunk not found: {chunk_id}")

        # Merge with existing metadata
        current_metadata = existing["metadatas"][0] if existing["metadatas"] else {}
        updated_metadata = {**current_metadata, **metadata_updates}

        collection.update(
            ids=[chunk_id],
            metadatas=[updated_metadata],
        )
        logger.debug(f"Updated metadata for chunk {chunk_id}: {list(metadata_updates.keys())}")

    async def batch_update_metadata(
        self,
        updates: list[tuple[str, dict[str, Any]]],
        batch_size: int = 100,
    ) -> int:
        """Batch update metadata for multiple chunks efficiently.

        Args:
            updates: List of (chunk_id, metadata_updates) tuples
            batch_size: Number of updates per batch

        Returns:
            Number of chunks updated
        """
        if not updates:
            return 0

        total_updated = 0
        for i in range(0, len(updates), batch_size):
            batch = updates[i:i + batch_size]
            ids = [chunk_id for chunk_id, _ in batch]

            # Get existing metadata for the batch
            collection = self._get_collection()
            existing = collection.get(ids=ids, include=["metadatas"])

            # Build updated metadata list
            existing_map = dict(zip(existing["ids"], existing["metadatas"] or [{}] * len(existing["ids"])))
            updated_metadatas = []
            valid_ids = []

            for chunk_id, metadata_updates in batch:
                if chunk_id in existing_map:
                    merged = {**existing_map[chunk_id], **metadata_updates}
                    updated_metadatas.append(merged)
                    valid_ids.append(chunk_id)
                else:
                    logger.warning(f"Chunk not found for batch update: {chunk_id}")

            if valid_ids:
                await self.update_metadata(valid_ids, updated_metadatas)
                total_updated += len(valid_ids)

            logger.debug(f"Batch updated {len(valid_ids)} chunks (batch {i // batch_size + 1})")

        logger.info(f"Batch update complete: {total_updated}/{len(updates)} chunks updated")
        return total_updated

    @with_retry(max_retries=3, base_delay=0.5)
    async def get_metadata(
        self,
        chunk_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        """Get metadata for chunks without fetching embeddings or documents.

        This is optimized for reading metadata (e.g., quality scores) without
        the overhead of fetching large embedding vectors.

        Args:
            chunk_ids: List of chunk IDs to retrieve metadata for

        Returns:
            Dictionary mapping chunk_id -> metadata dict
        """
        if not chunk_ids:
            return {}

        collection = self._get_collection()
        result = collection.get(
            ids=chunk_ids,
            include=["metadatas"],  # Only metadata, no documents or embeddings
        )

        return dict(zip(result["ids"], result["metadatas"] or []))

    async def get_quality_score(self, chunk_id: str) -> float | None:
        """Get the quality score for a single chunk.

        Args:
            chunk_id: The chunk ID

        Returns:
            Quality score (0-100) or None if not found
        """
        metadata = await self.get_metadata([chunk_id])
        if chunk_id in metadata:
            return metadata[chunk_id].get("quality_score")
        return None

    async def update_quality_score(
        self,
        chunk_id: str,
        new_score: float,
        increment_feedback_count: bool = True,
    ) -> None:
        """Update the quality score for a chunk.

        This is the primary method for updating quality scores since ChromaDB
        is the source of truth for quality data.

        Args:
            chunk_id: The chunk ID to update
            new_score: New quality score (will be clamped to 0-100)
            increment_feedback_count: Whether to increment the feedback counter
        """
        # Clamp score to valid range
        clamped_score = max(0.0, min(100.0, new_score))

        updates = {"quality_score": clamped_score}

        if increment_feedback_count:
            # Get current feedback count
            metadata = await self.get_metadata([chunk_id])
            if chunk_id in metadata:
                current_count = metadata[chunk_id].get("feedback_count", 0)
                updates["feedback_count"] = current_count + 1

        await self.update_single_metadata(chunk_id, updates)
        logger.info(f"Updated quality score for {chunk_id}: {clamped_score}")

    async def check_health(self) -> bool:
        """Check if ChromaDB is accessible.

        Returns:
            True if healthy, False otherwise
        """
        try:
            client = self._get_client()
            client.heartbeat()
            return True
        except Exception as e:
            logger.error(f"ChromaDB health check failed: {e}")
            return False

    def reset_collection(self) -> None:
        """Delete and recreate the collection (for reindexing)."""
        client = self._get_client()
        try:
            client.delete_collection(self.collection_name)
            logger.info(f"Deleted collection: {self.collection_name}")
        except Exception:
            pass  # Collection might not exist
        self._collection = None
        self._get_collection()
        logger.info(f"Created fresh collection: {self.collection_name}")
