"""Search API endpoint."""

import logging
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from knowledge_base.api.schemas import SearchRequest, SearchResponse, SearchResultItem
from knowledge_base.config import settings
from knowledge_base.search import BM25Index, HybridRetriever
from knowledge_base.vectorstore import VectorRetriever

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["search"])


# Simple in-memory rate limiter
_request_timestamps: dict[str, list[float]] = {}
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX = 60     # requests per window

def _check_rate_limit(client_ip: str) -> None:
    now = time.time()
    if client_ip not in _request_timestamps:
        _request_timestamps[client_ip] = []
    
    # Keep only timestamps within the window
    _request_timestamps[client_ip] = [
        t for t in _request_timestamps[client_ip] 
        if now - t < RATE_LIMIT_WINDOW
    ]
    
    if len(_request_timestamps[client_ip]) >= RATE_LIMIT_MAX:
        logger.warning(f"Rate limit exceeded for IP: {client_ip}")
        raise HTTPException(status_code=429, detail="Too many requests")
        
    _request_timestamps[client_ip].append(now)


def _apply_filters(
    results: list[SearchResultItem],
    filters: dict[str, Any],
) -> list[SearchResultItem]:
    """Apply metadata filters to search results.

    Supported filters:
    - space_key: Filter by Confluence space
    - doc_type: Filter by document type
    - topics: Filter by any matching topic (list)
    - updated_after: Filter by update date (ISO format string)
    """
    if not filters:
        return results

    filtered = []
    for result in results:
        metadata = result.metadata

        # Filter by space_key
        if "space_key" in filters:
            if metadata.get("space_key") != filters["space_key"]:
                continue

        # Filter by doc_type
        if "doc_type" in filters:
            if metadata.get("doc_type") != filters["doc_type"]:
                continue

        # Filter by topics (any match)
        if "topics" in filters:
            result_topics = metadata.get("topics", [])
            if isinstance(result_topics, str):
                result_topics = [result_topics]
            filter_topics = filters["topics"]
            if isinstance(filter_topics, str):
                filter_topics = [filter_topics]
            if not any(t in result_topics for t in filter_topics):
                continue

        # Filter by update date
        if "updated_after" in filters:
            updated_at = metadata.get("updated_at", "")
            if updated_at and updated_at < filters["updated_after"]:
                continue

        filtered.append(result)

    return filtered


def _to_result_item(result: Any, include_content: bool = True) -> SearchResultItem:
    """Convert a search result to SearchResultItem."""
    metadata = result.metadata if hasattr(result, "metadata") else {}

    # Build Confluence URL if we have the info
    url = metadata.get("url", "")
    if not url and metadata.get("page_id"):
        base_url = settings.CONFLUENCE_URL.rstrip("/")
        space_key = metadata.get("space_key", "")
        page_id = metadata.get("page_id", "")
        if space_key and page_id:
            url = f"{base_url}/wiki/spaces/{space_key}/pages/{page_id}"

    return SearchResultItem(
        chunk_id=result.chunk_id,
        page_id=metadata.get("page_id", ""),
        page_title=result.page_title if hasattr(result, "page_title") else metadata.get("page_title", ""),
        content=result.content if include_content else None,
        score=result.score,
        metadata=metadata,
        url=url,
    )


@router.post("/search", response_model=SearchResponse)
async def search(request: SearchRequest, raw_request: Request) -> SearchResponse:
    """Search the knowledge base.

    Supports three search methods:
    - **hybrid**: Combines BM25 keyword search with vector semantic search (recommended)
    - **vector**: Pure vector/semantic search
    - **bm25**: Pure keyword search

    Filters can be applied to narrow results by space, document type, topics, or date.
    """
    # Rate limit check
    client_ip = raw_request.client.host if raw_request.client else "unknown"
    _check_rate_limit(client_ip)

    start_time = time.time()

    try:
        if request.search_method == "hybrid":
            retriever = HybridRetriever()
            raw_results = await retriever.search(
                query=request.query,
                k=request.top_k * 2 if request.filters else request.top_k,  # Get more if filtering
            )

        elif request.search_method == "vector":
            retriever = VectorRetriever()
            raw_results = await retriever.search(
                query=request.query,
                n_results=request.top_k * 2 if request.filters else request.top_k,
            )

        elif request.search_method == "bm25":
            bm25 = BM25Index()
            if not bm25.load():
                raise HTTPException(
                    status_code=503,
                    detail="BM25 index not available. Run 'kb search rebuild-bm25' first.",
                )
            # BM25 returns tuples, convert to objects
            bm25_results = bm25.search_with_content(request.query, k=request.top_k * 2)
            raw_results = []
            for chunk_id, content, metadata, score in bm25_results:
                # Create a simple object with required attributes
                class BM25Result:
                    pass
                r = BM25Result()
                r.chunk_id = chunk_id
                r.content = content
                r.score = score
                r.metadata = metadata
                r.page_title = metadata.get("page_title", "")
                raw_results.append(r)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown search method: {request.search_method}",
            )

        # Convert to response items
        results = [_to_result_item(r, request.include_content) for r in raw_results]

        # Apply filters
        if request.filters:
            results = _apply_filters(results, request.filters)

        # Limit to requested count
        results = results[: request.top_k]

        took_ms = int((time.time() - start_time) * 1000)

        logger.info(
            f"Search completed: query='{request.query[:50]}...', "
            f"method={request.search_method}, results={len(results)}, took={took_ms}ms"
        )

        return SearchResponse(
            query=request.query,
            results=results,
            total_found=len(results),
            search_method=request.search_method,
            took_ms=took_ms,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Search failed: {e}", exc_info=True)
        # Sanitize error message in production
        detail = "Internal server error"
        if settings.DEBUG:
            detail = f"Search failed: {str(e)}"
            
        raise HTTPException(
            status_code=500,
            detail=detail,
        )


@router.get("/search/health")
async def search_health() -> dict[str, Any]:
    """Check search system health."""
    try:
        retriever = HybridRetriever()
        health = await retriever.check_health()

        return {
            "status": "healthy" if health.get("chroma_healthy") else "degraded",
            "bm25_indexed": health.get("bm25_indexed", 0),
            "bm25_built": health.get("bm25_built", False),
            "chroma_healthy": health.get("chroma_healthy", False),
            "embedding_provider": health.get("embedding_provider", "unknown"),
        }

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
        }
