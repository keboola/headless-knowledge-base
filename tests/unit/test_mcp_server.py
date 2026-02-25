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
os.environ.setdefault("MCP_OAUTH_CLIENT_SECRET", "test-client-secret")
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
# OAuth Authorization Server Metadata
# ===========================================================================


class TestOAuthAuthorizationServerMetadata:
    """Test GET /.well-known/oauth-authorization-server."""

    async def test_returns_metadata(self, client: AsyncClient):
        resp = await client.get("/.well-known/oauth-authorization-server")
        assert resp.status_code == 200
        body = resp.json()
        assert "issuer" in body
        assert "authorization_endpoint" in body
        assert "token_endpoint" in body
        assert "registration_endpoint" in body
        assert body["response_types_supported"] == ["code"]
        assert "S256" in body["code_challenge_methods_supported"]

    async def test_endpoints_use_base_url(self, client: AsyncClient):
        resp = await client.get("/.well-known/oauth-authorization-server")
        body = resp.json()
        assert body["authorization_endpoint"].endswith("/authorize")
        assert body["token_endpoint"].endswith("/token")
        assert body["registration_endpoint"].endswith("/register")


# ===========================================================================
# OAuth Authorize Endpoint
# ===========================================================================


class TestOAuthAuthorize:
    """Test GET /authorize - redirects to Google."""

    async def test_redirects_to_google(self, client: AsyncClient):
        resp = await client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": "test-client-id",
                "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
                "scope": "claudeai",
                "state": "test-state",
                "code_challenge": "abc123",
                "code_challenge_method": "S256",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        location = resp.headers["location"]
        assert "accounts.google.com" in location
        # Should map claudeai scope to Google scopes
        assert "openid" in location
        assert "email" in location
        assert "profile" in location
        # Should NOT contain the custom scope
        assert "claudeai" not in location
        # Should preserve PKCE params
        assert "code_challenge=abc123" in location
        assert "state=test-state" in location

    async def test_no_auth_required(self, client: AsyncClient):
        """The /authorize endpoint must be accessible without Bearer token."""
        resp = await client.get(
            "/authorize",
            params={"response_type": "code", "scope": "openid"},
            follow_redirects=False,
        )
        assert resp.status_code == 302


# ===========================================================================
# OAuth Token Endpoint
# ===========================================================================


class TestOAuthToken:
    """Test POST /token - proxies to Google."""

    async def test_proxies_to_google(self, client: AsyncClient):
        """Token endpoint should proxy to Google and return the response."""
        mock_google_response = MagicMock()
        mock_google_response.status_code = 200
        mock_google_response.json.return_value = {
            "access_token": "ya29.mock-token",
            "token_type": "Bearer",
            "expires_in": 3600,
            "id_token": "eyJ...",
        }

        with patch("knowledge_base.mcp.server.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_google_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            resp = await client.post(
                "/token",
                data={
                    "grant_type": "authorization_code",
                    "code": "test-auth-code",
                    "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
                    "code_verifier": "test-verifier",
                },
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["access_token"] == "ya29.mock-token"
        assert body["token_type"] == "Bearer"

    async def test_no_auth_required(self, client: AsyncClient):
        """The /token endpoint must be accessible without Bearer token."""
        mock_google_response = MagicMock()
        mock_google_response.status_code = 400
        mock_google_response.json.return_value = {"error": "invalid_grant"}

        with patch("knowledge_base.mcp.server.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_google_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            resp = await client.post(
                "/token",
                data={"grant_type": "authorization_code", "code": "bad-code"},
            )

        # Should NOT get 401 (auth not required), should get Google's error
        assert resp.status_code == 400


# ===========================================================================
# OAuth Dynamic Client Registration
# ===========================================================================


class TestOAuthRegister:
    """Test POST /register - returns our client_id."""

    async def test_returns_client_id(self, client: AsyncClient):
        resp = await client.post(
            "/register",
            json={
                "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"],
                "client_name": "Claude.AI",
                "grant_types": ["authorization_code"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["client_id"] == "test-client-id"
        assert body["client_name"] == "Claude.AI"
        assert "authorization_code" in body["grant_types"]

    async def test_no_auth_required(self, client: AsyncClient):
        """The /register endpoint must be accessible without Bearer token."""
        resp = await client.post(
            "/register",
            json={"redirect_uris": ["https://example.com/callback"]},
        )
        assert resp.status_code == 201


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
