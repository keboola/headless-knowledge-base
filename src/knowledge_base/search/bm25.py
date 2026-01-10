"""BM25 keyword search index for exact matching and abbreviations."""

import logging
import os
import pickle
import re
from pathlib import Path

from rank_bm25 import BM25Okapi

from knowledge_base.config import settings

logger = logging.getLogger(__name__)


class BM25Index:
    """BM25 keyword search index.

    Provides exact keyword matching to complement vector semantic search.
    Especially useful for abbreviations, product names, and technical terms.
    """

    def __init__(self, index_path: str | None = None):
        """Initialize BM25 index.

        Args:
            index_path: Path to persist/load the index. Defaults to config setting.
        """
        self.index_path = Path(index_path or settings.BM25_INDEX_PATH)
        self.index: BM25Okapi | None = None
        self.chunk_ids: list[str] = []
        self.chunk_contents: list[str] = []  # Store content for retrieval
        self.chunk_metadata: list[dict] = []  # Store metadata
        self.tokenized_corpus: list[list[str]] = []

    def build(
        self,
        chunk_ids: list[str],
        contents: list[str],
        metadatas: list[dict] | None = None,
    ) -> None:
        """Build BM25 index from chunks.

        Args:
            chunk_ids: List of chunk IDs
            contents: List of chunk text content
            metadatas: Optional list of metadata dicts for each chunk
        """
        if not chunk_ids or not contents:
            logger.warning("No chunks provided for BM25 index")
            return

        if len(chunk_ids) != len(contents):
            raise ValueError("chunk_ids and contents must have same length")

        self.chunk_ids = chunk_ids
        self.chunk_contents = contents
        self.chunk_metadata = metadatas or [{} for _ in chunk_ids]

        # Tokenize all documents
        self.tokenized_corpus = [self.tokenize(content) for content in contents]

        # Build BM25 index
        self.index = BM25Okapi(self.tokenized_corpus)

        logger.info(f"Built BM25 index with {len(chunk_ids)} documents")

    def search(self, query: str, k: int = 20) -> list[tuple[str, float]]:
        """Search the index and return (chunk_id, score) pairs.

        Args:
            query: Search query
            k: Maximum number of results to return

        Returns:
            List of (chunk_id, score) tuples, sorted by score descending
        """
        if self.index is None:
            logger.warning("BM25 index not built, returning empty results")
            return []

        tokenized_query = self.tokenize(query)

        if not tokenized_query:
            return []

        # Get BM25 scores for all documents
        scores = self.index.get_scores(tokenized_query)

        # Get top-k results with positive scores
        top_indices = scores.argsort()[-k:][::-1]

        results = []
        for i in top_indices:
            if scores[i] > 0:
                results.append((self.chunk_ids[i], float(scores[i])))

        return results

    def search_with_content(
        self, query: str, k: int = 20
    ) -> list[tuple[str, str, dict, float]]:
        """Search and return results with content and metadata.

        Args:
            query: Search query
            k: Maximum number of results

        Returns:
            List of (chunk_id, content, metadata, score) tuples
        """
        if self.index is None:
            return []

        tokenized_query = self.tokenize(query)
        if not tokenized_query:
            return []

        scores = self.index.get_scores(tokenized_query)
        top_indices = scores.argsort()[-k:][::-1]

        results = []
        for i in top_indices:
            if scores[i] > 0:
                results.append((
                    self.chunk_ids[i],
                    self.chunk_contents[i],
                    self.chunk_metadata[i],
                    float(scores[i]),
                ))

        return results

    def tokenize(self, text: str) -> list[str]:
        """Tokenize text for BM25.

        Simple tokenization: lowercase, split on whitespace and punctuation,
        remove very short tokens.

        Args:
            text: Text to tokenize

        Returns:
            List of tokens
        """
        # Lowercase and split on non-alphanumeric (keep alphanumeric sequences)
        tokens = re.findall(r"[a-zA-Z0-9]+", text.lower())

        # Filter very short tokens (single chars except common abbreviations)
        tokens = [t for t in tokens if len(t) > 1 or t in ("i", "a")]

        return tokens

    def save(self) -> None:
        """Save the index to disk."""
        if self.index is None:
            logger.warning("No index to save")
            return

        # Ensure directory exists
        self.index_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "chunk_ids": self.chunk_ids,
            "chunk_contents": self.chunk_contents,
            "chunk_metadata": self.chunk_metadata,
            "tokenized_corpus": self.tokenized_corpus,
        }

        with open(self.index_path, "wb") as f:
            pickle.dump(data, f)

        logger.info(f"Saved BM25 index to {self.index_path}")

    def load(self) -> bool:
        """Load the index from disk.

        Returns:
            True if loaded successfully, False otherwise
        """
        if not self.index_path.exists():
            logger.info(f"No BM25 index found at {self.index_path}")
            return False

        try:
            with open(self.index_path, "rb") as f:
                data = pickle.load(f)

            self.chunk_ids = data["chunk_ids"]
            self.chunk_contents = data["chunk_contents"]
            self.chunk_metadata = data.get("chunk_metadata", [{} for _ in self.chunk_ids])
            self.tokenized_corpus = data["tokenized_corpus"]

            # Rebuild BM25 from tokenized corpus
            self.index = BM25Okapi(self.tokenized_corpus)

            logger.info(f"Loaded BM25 index with {len(self.chunk_ids)} documents")
            return True

        except Exception as e:
            logger.error(f"Failed to load BM25 index: {e}")
            return False

    @property
    def is_built(self) -> bool:
        """Check if the index is built."""
        return self.index is not None and len(self.chunk_ids) > 0

    def __len__(self) -> int:
        """Return number of indexed documents."""
        return len(self.chunk_ids)
