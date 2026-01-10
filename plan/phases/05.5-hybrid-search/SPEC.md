# Phase 05.5: Hybrid Search

## Overview

Add BM25 keyword search alongside vector search, combining both for better retrieval of abbreviations, exact matches, and semantic content.

## Dependencies

- **Requires**: Phase 05 (Vector Indexing)
- **Blocks**: None (enhancement to Phase 06)
- **Enhances**: Search API quality

## Deliverables

```
src/knowledge_base/
├── search/
│   ├── __init__.py
│   ├── bm25.py               # BM25 index and search
│   ├── hybrid.py             # Combine BM25 + vector
│   └── fusion.py             # Reciprocal Rank Fusion
```

## Technical Specification

### BM25 Index

```python
from rank_bm25 import BM25Okapi

class BM25Index:
    def __init__(self):
        self.index = None
        self.chunk_ids = []
        self.tokenized_corpus = []

    def build(self, chunks: list[Chunk]):
        """Build BM25 index from chunks."""
        self.chunk_ids = [c.chunk_id for c in chunks]
        self.tokenized_corpus = [
            self.tokenize(c.content) for c in chunks
        ]
        self.index = BM25Okapi(self.tokenized_corpus)

    def search(self, query: str, k: int = 20) -> list[tuple[str, float]]:
        """Search and return (chunk_id, score) pairs."""
        tokenized_query = self.tokenize(query)
        scores = self.index.get_scores(tokenized_query)

        # Get top-k results
        top_indices = scores.argsort()[-k:][::-1]
        return [
            (self.chunk_ids[i], scores[i])
            for i in top_indices
            if scores[i] > 0
        ]

    def tokenize(self, text: str) -> list[str]:
        """Simple tokenization - lowercase, split, remove punctuation."""
        return text.lower().split()
```

### Hybrid Retriever

```python
class HybridRetriever:
    def __init__(
        self,
        bm25: BM25Index,
        vector_store: ChromaClient,
        embeddings: BaseEmbeddings
    ):
        self.bm25 = bm25
        self.vector_store = vector_store
        self.embeddings = embeddings

    async def search(
        self,
        query: str,
        k: int = 10,
        bm25_weight: float = 0.3,
        vector_weight: float = 0.7
    ) -> list[SearchResult]:
        """Combine BM25 and vector search results."""

        # BM25 search
        bm25_results = self.bm25.search(query, k=k*2)

        # Vector search
        query_embedding = await self.embeddings.embed([query])
        vector_results = self.vector_store.collection.query(
            query_embeddings=query_embedding,
            n_results=k*2
        )

        # Combine with RRF
        combined = reciprocal_rank_fusion(
            bm25_results,
            vector_results,
            weights=(bm25_weight, vector_weight)
        )

        return combined[:k]
```

### Reciprocal Rank Fusion

```python
def reciprocal_rank_fusion(
    *result_lists: list[tuple[str, float]],
    weights: tuple[float, ...] = None,
    k: int = 60
) -> list[tuple[str, float]]:
    """Combine ranked lists using RRF.

    RRF score = sum(weight / (k + rank))
    """
    if weights is None:
        weights = tuple(1.0 for _ in result_lists)

    scores = defaultdict(float)

    for weight, results in zip(weights, result_lists):
        for rank, (doc_id, _) in enumerate(results):
            scores[doc_id] += weight / (k + rank + 1)

    return sorted(scores.items(), key=lambda x: x[1], reverse=True)
```

### Why Hybrid Search?

| Query Type | BM25 Strength | Vector Strength |
|------------|--------------|-----------------|
| Abbreviations ("GCP", "PTO") | Exact match | May miss |
| Product names ("Snowflake") | Exact match | Good |
| Conceptual ("how to take vacation") | Weak | Strong |
| Code/technical ("def function") | Exact match | Moderate |

### CLI Commands

```bash
# Rebuild BM25 index
python -m knowledge_base.cli search rebuild-bm25

# Test hybrid search
python -m knowledge_base.cli search query "How do I request PTO?" --verbose
```

## Configuration

```bash
SEARCH_BM25_WEIGHT=0.3
SEARCH_VECTOR_WEIGHT=0.7
SEARCH_TOP_K=10
```

## Definition of Done

- [ ] BM25 index built from all chunks
- [ ] Hybrid search combines both methods
- [ ] RRF fusion working correctly
- [ ] Abbreviations found (test: "PTO", "GCP")
- [ ] Semantic queries work (test: "how to take vacation")
