"""Health check endpoints for the knowledge base API."""

from typing import Any

import redis.asyncio as redis
from fastapi import APIRouter

from knowledge_base.config import settings
from knowledge_base.rag.factory import get_llm
from knowledge_base.rag.exceptions import LLMProviderNotConfiguredError

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Basic health check - returns ok if the service is running."""
    return {"status": "ok"}


@router.get("/health/ready")
async def ready() -> dict[str, Any]:
    """
    Readiness check - verifies all dependent services are available.

    Checks:
    - Graphiti: Graph database connection (Kuzu/Neo4j)
    - Redis: Task queue broker connection
    - LLM: Language model provider connection (Claude, Ollama, etc.)
    """
    services: dict[str, str] = {}
    all_ok = True

    # Check Graphiti (graph database)
    try:
        from knowledge_base.graph.graphiti_client import get_graphiti_client

        if settings.GRAPH_ENABLE_GRAPHITI:
            client = get_graphiti_client()
            # For Kuzu, check if client was created successfully
            # For Neo4j, this would verify the connection
            services["graphiti"] = f"ok ({settings.GRAPH_BACKEND})"
        else:
            services["graphiti"] = "disabled"
            all_ok = False
    except Exception as e:
        services["graphiti"] = f"error: {type(e).__name__}"
        all_ok = False

    # Check Redis
    try:
        redis_client = redis.from_url(settings.REDIS_URL)
        pong = await redis_client.ping()
        await redis_client.aclose()
        if pong:
            services["redis"] = "ok"
        else:
            services["redis"] = "error: no response"
            all_ok = False
    except Exception as e:
        services["redis"] = f"error: {type(e).__name__}"
        all_ok = False

    # Check LLM (provider-agnostic)
    try:
        llm = await get_llm()
        if await llm.check_health():
            services["llm"] = f"ok ({llm.provider_name})"
        else:
            services["llm"] = f"error: {llm.provider_name} not healthy"
            all_ok = False
    except LLMProviderNotConfiguredError:
        services["llm"] = "warning: no provider configured"
        # Don't fail health check if no LLM - it may be optional for some deployments
    except Exception as e:
        services["llm"] = f"error: {type(e).__name__}"
        all_ok = False

    status = "ready" if all_ok else "degraded"
    return {"status": status, "services": services}
