"""Health check endpoints for the knowledge base API."""

from typing import Any

import httpx
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
    - ChromaDB: Vector database connection
    - Redis: Task queue broker connection
    - LLM: Language model provider connection (Claude, Ollama, etc.)
    """
    services: dict[str, str] = {}
    all_ok = True

    # Check ChromaDB
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"http://{settings.CHROMA_HOST}:{settings.CHROMA_PORT}/api/v1/heartbeat"
            )
            if response.status_code == 200:
                services["chromadb"] = "ok"
            else:
                services["chromadb"] = f"error: status {response.status_code}"
                all_ok = False
    except Exception as e:
        services["chromadb"] = f"error: {type(e).__name__}"
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
