"""Tests for health check endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient

from knowledge_base.main import app


@pytest.fixture
async def client():
    """Create an async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    """Test basic health endpoint returns ok."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_root(client: AsyncClient):
    """Test root endpoint returns app info."""
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "name" in data
    assert "version" in data
    assert "streamlit_ui" in data


@pytest.mark.asyncio
async def test_health_ready_returns_services(client: AsyncClient):
    """Test readiness endpoint returns service statuses.

    Note: This test checks structure only - actual services won't be running in test env.
    """
    response = await client.get("/health/ready")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "services" in data
    assert "chromadb" in data["services"]
    assert "redis" in data["services"]
    assert "llm" in data["services"]  # Provider-agnostic LLM check
