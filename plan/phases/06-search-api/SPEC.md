# Phase 06: Search API

## Overview

Create REST API endpoint for semantic search, returning ranked results with metadata.

## Dependencies

- **Requires**: Phase 05 (Vector Indexing), Phase 05.5 (Hybrid Search)
- **Blocks**: Phase 07 (RAG Answers)

## Deliverables

```
src/knowledge_base/
├── api/
│   ├── search.py             # Search endpoint
│   └── schemas.py            # Request/response models
├── vectorstore/
│   └── retriever.py          # Search orchestration
```

## Technical Specification

### API Endpoint

```
POST /api/v1/search
```

### Request Schema

```python
class SearchRequest(BaseModel):
    query: str                          # User's question
    top_k: int = 10                     # Number of results
    filters: dict | None = None         # Metadata filters
    include_content: bool = True        # Include chunk content
    search_method: str = "hybrid"       # "hybrid", "vector", "bm25"
```

### Response Schema

```python
class SearchResult(BaseModel):
    chunk_id: str
    page_id: str
    page_title: str
    content: str | None
    score: float
    metadata: dict                      # topics, doc_type, etc.
    url: str                            # Confluence link

class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
    total_found: int
    search_method: str
    took_ms: int
```

### Retriever

```python
class Retriever:
    def __init__(self, hybrid: HybridRetriever, chroma: ChromaClient):
        self.hybrid = hybrid
        self.chroma = chroma

    async def search(
        self,
        query: str,
        top_k: int = 10,
        filters: dict | None = None,
        method: str = "hybrid"
    ) -> list[SearchResult]:
        """Execute search and enrich results."""

        # Get results based on method
        if method == "hybrid":
            results = await self.hybrid.search(query, k=top_k)
        elif method == "vector":
            results = await self.vector_search(query, k=top_k)
        else:
            results = await self.bm25_search(query, k=top_k)

        # Apply metadata filters
        if filters:
            results = self.apply_filters(results, filters)

        # Enrich with full metadata
        return await self.enrich_results(results)
```

### Metadata Filters

```python
# Filter by space
{"space_key": "ENG"}

# Filter by document type
{"doc_type": "policy"}

# Filter by topic (any match)
{"topics": ["onboarding", "benefits"]}

# Combined filters
{
    "space_key": "HR",
    "doc_type": "policy",
    "updated_after": "2024-01-01"
}
```

### API Handler

```python
@router.post("/api/v1/search", response_model=SearchResponse)
async def search(request: SearchRequest):
    start = time.time()

    results = await retriever.search(
        query=request.query,
        top_k=request.top_k,
        filters=request.filters,
        method=request.search_method
    )

    if not request.include_content:
        for r in results:
            r.content = None

    return SearchResponse(
        query=request.query,
        results=results,
        total_found=len(results),
        search_method=request.search_method,
        took_ms=int((time.time() - start) * 1000)
    )
```

## Example Usage

```bash
curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "How do I request PTO?",
    "top_k": 5,
    "filters": {"space_key": "HR"}
  }'
```

## Definition of Done

- [ ] Search endpoint accepts queries
- [ ] Returns ranked results with scores
- [ ] Metadata filters work correctly
- [ ] Response includes Confluence URLs
- [ ] Performance < 500ms for typical queries
