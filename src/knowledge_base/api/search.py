"""Search API endpoint."""

import logging
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from knowledge_base.api.schemas import SearchRequest, SearchResponse, SearchResultItem
from knowledge_base.config import settings
from knowledge_base.search import HybridRetriever

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

    Uses Graphiti's unified hybrid search combining:
    - **semantic**: Vector similarity search (embeddings)
    - **keyword**: BM25 keyword matching
    - **graph**: Relationship-aware retrieval

    Note: The search_method parameter is deprecated. All methods now use
    Graphiti's hybrid search for best results.

    Filters can be applied to narrow results by space, document type, topics, or date.
    """
    # Rate limit check
    client_ip = raw_request.client.host if raw_request.client else "unknown"
    _check_rate_limit(client_ip)

    start_time = time.time()

    try:
        # All search methods now use Graphiti's hybrid search
        retriever = HybridRetriever()
        raw_results = await retriever.search(
            query=request.query,
            k=request.top_k * 2 if request.filters else request.top_k,  # Get more if filtering
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
            "status": "healthy" if health.get("graphiti_healthy") else "degraded",
            "graphiti_enabled": health.get("graphiti_enabled", False),
            "graphiti_healthy": health.get("graphiti_healthy", False),
            "backend": health.get("backend", "unknown"),
        }

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
        }
