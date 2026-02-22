"""Tests for MCP HTTP server endpoints and JSON-RPC protocol."""

import os
import sys
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Set required env vars BEFORE importing server module, because server.py
# instantiates MCPSettings() at module level which requires these.
os.environ.setdefault("MCP_OAUTH_CLIENT_ID", "test-client-id")
os.environ.setdefault("MCP_OAUTH_RESOURCE_IDENTIFIER", "https://test-kb-mcp.example.com")
os.environ.setdefault("MCP_DEV_MODE", "true")

from httpx import ASGITransport, AsyncClient

from knowledge_base.mcp.server import app, mcp_settings  # noqa: E402


@dataclass
class _FakeSearchResult:
    """Minimal stand-in for SearchResult."""

    chunk_id: str
    content: str
    score: float
    metadata: dict[str, Any]

    @property
    def page_title(self) -> str:
        return self.metadata.get("page_title", "")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def dev_auth_header() -> dict[str, str]:
    """Bearer token header -- value is irrelevant in dev mode."""
    return {"Authorization": "Bearer dev-token-placeholder"}


@pytest.fixture
async def client():
    """httpx AsyncClient wired to the FastAPI app with dev mode enabled."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ===========================================================================
# Health & Metadata Endpoints
# ===========================================================================


class TestHealthEndpoint:
    """Test GET /health."""

    async def test_health_returns_200(self, client: AsyncClient):
        resp = await client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        assert body["service"] == "knowledge-base-mcp-server"


class TestOAuthMetadataEndpoint:
    """Test GET /.well-known/oauth-protected-resource."""

    async def test_returns_metadata(self, client: AsyncClient):
        resp = await client.get("/.well-known/oauth-protected-resource")
        assert resp.status_code == 200
        body = resp.json()
        assert "resource" in body
        assert "authorization_servers" in body


# ===========================================================================
# Authentication
# ===========================================================================


class TestAuthentication:
    """Test authentication middleware."""

    async def test_post_mcp_without_auth_returns_401(self, client: AsyncClient):
        """POST /mcp without Authorization header should return 401."""
        resp = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "ping", "id": 1},
        )
        assert resp.status_code == 401

    async def test_post_mcp_with_invalid_auth_scheme_returns_401(self, client: AsyncClient):
        """POST /mcp with non-Bearer auth should return 401."""
        resp = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "ping", "id": 1},
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
        )
        assert resp.status_code == 401


# ===========================================================================
# MCP Protocol: initialize
# ===========================================================================


class TestMCPInitialize:
    """Test MCP initialize method."""

    async def test_initialize_returns_protocol_version(
        self, client: AsyncClient, dev_auth_header: dict
    ):
        resp = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "initialize", "id": 1},
            headers=dev_auth_header,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["jsonrpc"] == "2.0"
        assert body["id"] == 1
        result = body["result"]
        assert result["protocolVersion"] == "2024-11-05"
        assert "tools" in result["capabilities"]
        assert result["serverInfo"]["name"] == "keboola-knowledge-base"


# ===========================================================================
# MCP Protocol: tools/list
# ===========================================================================


class TestMCPToolsList:
    """Test MCP tools/list method."""

    async def test_tools_list_returns_all_tools_in_dev_mode(
        self, client: AsyncClient, dev_auth_header: dict
    ):
        """Dev mode grants all scopes, so all 6 tools should be listed."""
        resp = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 2},
            headers=dev_auth_header,
        )
        assert resp.status_code == 200
        body = resp.json()
        tools = body["result"]["tools"]
        assert len(tools) == 6
        names = {t["name"] for t in tools}
        assert "ask_question" in names
        assert "search_knowledge" in names
        assert "create_knowledge" in names

    async def test_tools_list_each_tool_has_schema(
        self, client: AsyncClient, dev_auth_header: dict
    ):
        """Each tool in the list should have name, description, and inputSchema."""
        resp = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 3},
            headers=dev_auth_header,
        )
        tools = resp.json()["result"]["tools"]
        for tool in tools:
            assert "name" in tool
            assert "description" in tool
            assert "inputSchema" in tool


class TestMCPToolsListScopeFiltering:
    """Test that tools/list respects user scopes."""

    async def test_read_only_user_sees_fewer_tools(self):
        """A user with only kb.read should see only read tools."""
        from knowledge_base.mcp import server as srv_module

        original_fn = srv_module.handle_tools_list

        async def _custom_handle(user):
            # Force read-only scopes
            user = {**user, "scopes": ["kb.read"]}
            return await original_fn(user)

        with patch.object(srv_module, "handle_tools_list", side_effect=_custom_handle):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.post(
                    "/mcp",
                    json={"jsonrpc": "2.0", "method": "tools/list", "id": 4},
                    headers={"Authorization": "Bearer dev-token"},
                )

        assert resp.status_code == 200
        tools = resp.json()["result"]["tools"]
        names = {t["name"] for t in tools}
        assert names == {"ask_question", "search_knowledge", "check_health"}


# ===========================================================================
# MCP Protocol: tools/call
# ===========================================================================


class TestMCPToolsCall:
    """Test MCP tools/call method."""

    async def test_tools_call_search_knowledge(
        self, client: AsyncClient, dev_auth_header: dict
    ):
        """tools/call search_knowledge should execute and return content."""
        fake_results = [
            _FakeSearchResult(
                chunk_id="c1",
                content="Keboola overview content",
                score=0.9,
                metadata={"page_title": "Overview", "url": "https://wiki.keboola.com"},
            ),
        ]

        with patch(
            "knowledge_base.core.qa.search_knowledge",
            new_callable=AsyncMock,
            return_value=fake_results,
        ):
            resp = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {
                        "name": "search_knowledge",
                        "arguments": {"query": "Keboola overview"},
                    },
                    "id": 5,
                },
                headers=dev_auth_header,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == 5
        content = body["result"]["content"]
        assert len(content) >= 1
        assert content[0]["type"] == "text"
        assert "Found 1 results" in content[0]["text"]

    async def test_tools_call_missing_name_returns_error(
        self, client: AsyncClient, dev_auth_header: dict
    ):
        """tools/call without a tool name should return an error."""
        resp = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"arguments": {}},
                "id": 6,
            },
            headers=dev_auth_header,
        )
        assert resp.status_code == 200
        body = resp.json()
        # Should be an error response (code -32000 from HTTPException)
        assert body["error"] is not None
        assert body["error"]["code"] == -32000


# ===========================================================================
# MCP Protocol: ping
# ===========================================================================


class TestMCPPing:
    """Test MCP ping method."""

    async def test_ping_returns_empty_result(
        self, client: AsyncClient, dev_auth_header: dict
    ):
        resp = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "ping", "id": 7},
            headers=dev_auth_header,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["result"] == {}
        assert body["id"] == 7


# ===========================================================================
# MCP Protocol: unknown method
# ===========================================================================


class TestMCPUnknownMethod:
    """Test unknown MCP methods."""

    async def test_unknown_method_returns_error_code(
        self, client: AsyncClient, dev_auth_header: dict
    ):
        resp = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "totally/unknown", "id": 8},
            headers=dev_auth_header,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["error"]["code"] == -32601
        assert "Method not found" in body["error"]["message"]
