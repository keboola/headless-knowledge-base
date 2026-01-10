"""Analyze documentation gaps from unanswered or poorly-answered queries."""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_base.db.models import DocumentationGap, EvalResult, QueryRecord

if TYPE_CHECKING:
    from knowledge_base.vectorstore.embeddings import BaseEmbeddings

logger = logging.getLogger(__name__)

# Default thresholds
DEFAULT_MIN_CLUSTER_SIZE = 3
DEFAULT_SIMILARITY_THRESHOLD = 0.75
DEFAULT_QUALITY_THRESHOLD = 0.5


@dataclass
class QueryCluster:
    """A cluster of similar queries."""

    queries: list[str]
    representative_query: str
    avg_quality: float = 0.0

    @property
    def size(self) -> int:
        return len(self.queries)


@dataclass
class GapInfo:
    """Information about a documentation gap."""

    topic: str
    query_count: int
    sample_queries: list[str]
    suggested_title: str | None = None
    avg_quality: float = 0.0


class GapAnalyzer:
    """Analyze documentation gaps from failed or low-quality queries."""

    def __init__(
        self,
        session: Session,
        embeddings: "BaseEmbeddings | None" = None,
        min_cluster_size: int = DEFAULT_MIN_CLUSTER_SIZE,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
        quality_threshold: float = DEFAULT_QUALITY_THRESHOLD,
    ):
        """Initialize gap analyzer.

        Args:
            session: Database session
            embeddings: Embedding model for clustering (optional)
            min_cluster_size: Minimum queries to form a gap
            similarity_threshold: Cosine similarity threshold for clustering
            quality_threshold: Maximum quality score to consider as gap
        """
        self.session = session
        self.embeddings = embeddings
        self.min_cluster_size = min_cluster_size
        self.similarity_threshold = similarity_threshold
        self.quality_threshold = quality_threshold

    def find_gaps(self, days: int = 30) -> list[GapInfo]:
        """Find documentation gaps from recent low-quality queries.

        Args:
            days: Number of days to look back

        Returns:
            List of GapInfo sorted by query count
        """
        # Get failed/low-quality queries
        failed_queries = self._get_low_quality_queries(days)

        if not failed_queries:
            logger.info("No low-quality queries found")
            return []

        logger.info(f"Found {len(failed_queries)} low-quality queries")

        # Cluster similar queries
        if self.embeddings:
            clusters = self._cluster_queries_with_embeddings(failed_queries)
        else:
            clusters = self._cluster_queries_simple(failed_queries)

        # Convert to gaps
        gaps = []
        for cluster in clusters:
            if cluster.size >= self.min_cluster_size:
                gaps.append(
                    GapInfo(
                        topic=cluster.representative_query,
                        query_count=cluster.size,
                        sample_queries=cluster.queries[:5],
                        suggested_title=self._generate_title(cluster),
                        avg_quality=cluster.avg_quality,
                    )
                )

        # Sort by query count (most common gaps first)
        gaps.sort(key=lambda g: g.query_count, reverse=True)

        logger.info(f"Identified {len(gaps)} documentation gaps")
        return gaps

    def _get_low_quality_queries(self, days: int) -> list[tuple[str, float]]:
        """Get queries with low evaluation scores.

        Returns:
            List of (query, quality_score) tuples
        """
        since = datetime.utcnow() - timedelta(days=days)

        # Get evaluated queries with low scores
        results = self.session.execute(
            select(QueryRecord.query, EvalResult.overall)
            .join(EvalResult, QueryRecord.query_id == EvalResult.query_id)
            .where(QueryRecord.created_at >= since)
            .where(EvalResult.overall < self.quality_threshold)
        ).all()

        return [(r[0], r[1]) for r in results]

    def _cluster_queries_simple(
        self, queries: list[tuple[str, float]]
    ) -> list[QueryCluster]:
        """Simple clustering based on word overlap."""
        clusters: list[QueryCluster] = []
        used: set[int] = set()

        for i, (q1, score1) in enumerate(queries):
            if i in used:
                continue

            cluster_queries = [q1]
            cluster_scores = [score1]
            used.add(i)

            words1 = set(q1.lower().split())

            for j, (q2, score2) in enumerate(queries):
                if j in used:
                    continue

                words2 = set(q2.lower().split())
                overlap = len(words1 & words2) / max(len(words1 | words2), 1)

                if overlap > 0.5:
                    cluster_queries.append(q2)
                    cluster_scores.append(score2)
                    used.add(j)

            clusters.append(
                QueryCluster(
                    queries=cluster_queries,
                    representative_query=cluster_queries[0],
                    avg_quality=sum(cluster_scores) / len(cluster_scores),
                )
            )

        return clusters

    def _cluster_queries_with_embeddings(
        self, queries: list[tuple[str, float]]
    ) -> list[QueryCluster]:
        """Cluster queries using embedding similarity."""
        if not self.embeddings:
            return self._cluster_queries_simple(queries)

        query_texts = [q[0] for q in queries]
        scores = [q[1] for q in queries]

        # Get embeddings
        try:
            embeddings = self.embeddings.embed(query_texts)
        except Exception as e:
            logger.warning(f"Embedding failed, falling back to simple clustering: {e}")
            return self._cluster_queries_simple(queries)

        clusters: list[QueryCluster] = []
        used: set[int] = set()

        for i in range(len(query_texts)):
            if i in used:
                continue

            cluster_indices = [i]
            used.add(i)

            for j in range(len(query_texts)):
                if j in used:
                    continue

                similarity = self._cosine_similarity(embeddings[i], embeddings[j])
                if similarity > self.similarity_threshold:
                    cluster_indices.append(j)
                    used.add(j)

            cluster_queries = [query_texts[idx] for idx in cluster_indices]
            cluster_scores = [scores[idx] for idx in cluster_indices]

            clusters.append(
                QueryCluster(
                    queries=cluster_queries,
                    representative_query=cluster_queries[0],
                    avg_quality=sum(cluster_scores) / len(cluster_scores),
                )
            )

        return clusters

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        a_arr = np.array(a)
        b_arr = np.array(b)
        return float(np.dot(a_arr, b_arr) / (np.linalg.norm(a_arr) * np.linalg.norm(b_arr)))

    def _generate_title(self, cluster: QueryCluster) -> str:
        """Generate a suggested document title from cluster."""
        # Simple approach: use representative query as title
        title = cluster.representative_query

        # Clean up
        title = title.strip().rstrip("?")

        # Capitalize first letter
        if title:
            title = title[0].upper() + title[1:]

        # Add prefix
        return f"Guide: {title}"

    def save_gaps(self, gaps: list[GapInfo]) -> int:
        """Save identified gaps to database.

        Args:
            gaps: List of gaps to save

        Returns:
            Number of gaps saved
        """
        saved = 0

        for gap in gaps:
            # Check if similar gap already exists
            existing = self.session.execute(
                select(DocumentationGap).where(
                    DocumentationGap.topic == gap.topic,
                    DocumentationGap.status == "open",
                )
            ).scalar_one_or_none()

            if existing:
                # Update query count
                existing.query_count = gap.query_count
                existing.sample_queries = json.dumps(gap.sample_queries)
            else:
                # Create new gap
                db_gap = DocumentationGap(
                    topic=gap.topic,
                    suggested_title=gap.suggested_title,
                    query_count=gap.query_count,
                    sample_queries=json.dumps(gap.sample_queries),
                )
                self.session.add(db_gap)
                saved += 1

        self.session.commit()
        logger.info(f"Saved {saved} new documentation gaps")

        return saved

    def get_open_gaps(self) -> list[DocumentationGap]:
        """Get all open documentation gaps."""
        return list(
            self.session.execute(
                select(DocumentationGap)
                .where(DocumentationGap.status == "open")
                .order_by(DocumentationGap.query_count.desc())
            ).scalars().all()
        )
