"""MCP HTTP Server with OAuth 2.1 for Knowledge Base.

Provides Streamable HTTP transport for MCP protocol with Google OAuth authentication.
Acts as both OAuth Authorization Server (proxying to Google) and Resource Server.
Compatible with Claude.AI remote MCP server integration.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, Optional
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from knowledge_base.mcp.config import (
    MCPSettings,
    OAUTH_SCOPES,
    TOOL_SCOPE_REQUIREMENTS,
    check_scope_access,
)
from knowledge_base.mcp.oauth.metadata import ProtectedResourceMetadata
from knowledge_base.mcp.oauth.resource_server import (
    OAuthResourceServer,
    extract_user_context,
)
from knowledge_base.mcp.tools import TOOLS, execute_tool, get_tools_for_scopes

logger = logging.getLogger(__name__)

# Initialize settings
mcp_settings = MCPSettings()


def _get_oauth_audience() -> str:
    """Get OAuth audience. For Google OAuth, audience is the client_id."""
    return mcp_settings.MCP_OAUTH_CLIENT_ID


def _get_advertised_scopes() -> list[str]:
    """Get scopes to advertise. Google only understands standard OpenID scopes."""
    return ["openid", "email", "profile"]


# Token validation uses Google as the issuer (they issue the JWTs).
# The protected resource metadata is built dynamically in the endpoint
# to advertise THIS server as the OAuth AS (since we proxy to Google).
resource_server = OAuthResourceServer(
    resource=mcp_settings.MCP_OAUTH_RESOURCE_IDENTIFIER,
    authorization_servers=[mcp_settings.MCP_OAUTH_ISSUER],
    audience=_get_oauth_audience(),
    scopes_supported=_get_advertised_scopes(),
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    from knowledge_base.db.database import init_db
    await init_db()
    logger.info("Database initialized at startup")

    logger.info(f"MCP Server started on {mcp_settings.MCP_HOST}:{mcp_settings.MCP_PORT}")

    yield


# Create FastAPI app
app = FastAPI(
    title="Knowledge Base MCP Server",
    description="MCP server for Keboola AI Knowledge Base with OAuth 2.1 authentication",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://claude.ai", "https://www.claude.ai"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# OAuth Middleware
# =============================================================================


@app.middleware("http")
async def oauth_middleware(request: Request, call_next):
    """OAuth authentication middleware."""
    skip_paths = [
        "/health",
        "/.well-known/oauth-protected-resource",
        "/.well-known/oauth-authorization-server",
        "/authorize",
        "/token",
        "/register",
        "/callback",
    ]
    if request.url.path in skip_paths:
        return await call_next(request)

    # Extract Bearer token
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse(
            status_code=401,
            content={"error": "unauthorized", "error_description": "Missing Bearer token"},
            headers={"WWW-Authenticate": 'Bearer realm="knowledge-base-mcp"'},
        )

    token = auth_header[7:]

    # Dev mode: skip validation
    if mcp_settings.MCP_DEV_MODE:
        import os

        dev_email = os.getenv("TEST_USER_EMAIL", "dev@keboola.com")
        request.state.user = {
            "sub": "dev-user",
            "email": dev_email,
            "scopes": list(OAUTH_SCOPES.keys()),
            "claims": {},
        }
        return await call_next(request)

    # Validate token
    if resource_server:
        try:
            claims = await resource_server.validate_token_async(token)
            request.state.user = extract_user_context(claims)
            return await call_next(request)
        except Exception:
            return JSONResponse(
                status_code=401,
                content={"error": "invalid_token", "error_description": "Token validation failed"},
                headers={
                    "WWW-Authenticate": 'Bearer realm="knowledge-base-mcp", error="invalid_token"'
                },
            )

    return await call_next(request)


# =============================================================================
# Health & Metadata Endpoints
# =============================================================================


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "knowledge-base-mcp-server"}


@app.get("/.well-known/oauth-protected-resource")
async def oauth_protected_resource_metadata(request: Request):
    """RFC 9728 Protected Resource Metadata endpoint.

    The authorization_servers field must point to THIS server (the MCP server
    acts as OAuth AS, proxying to Google). We derive the URL from the request
    so it works regardless of Cloud Run URL vs custom domain.
    """
    base_url = _get_base_url(request)
    return {
        "resource": base_url,
        "authorization_servers": [base_url],
        "scopes_supported": list(OAUTH_SCOPES.keys()),
        "bearer_methods_supported": ["header"],
        "resource_signing_alg_values_supported": ["RS256", "ES256"],
    }


@app.get("/callback")
async def oauth_callback(code: str = None, state: str = None, error: str = None):
    """OAuth authorization code callback (for browser popup flows)."""
    if error:
        return HTMLResponse(
            content=f"<html><body><h1>OAuth Error</h1><p>{error}</p></body></html>",
            status_code=400,
        )

    if code:
        return HTMLResponse(
            content="""
            <html>
            <body>
            <h1>Authorization Successful</h1>
            <p>You can close this window and return to Claude.</p>
            <script>
                if (window.opener) {
                    window.opener.postMessage({type: 'oauth_callback', code: '%s', state: '%s'}, '*');
                }
            </script>
            </body>
            </html>
            """
            % (code, state or ""),
            status_code=200,
        )

    return HTMLResponse(
        content="<html><body><h1>OAuth Callback</h1></body></html>",
        status_code=200,
    )


# =============================================================================
# OAuth Authorization Server Endpoints (proxy to Google)
# =============================================================================
# The MCP spec requires the MCP server to act as an OAuth Authorization Server.
# Claude.AI discovers these endpoints via /.well-known/oauth-authorization-server
# or falls back to default paths (/authorize, /token, /register).
# We proxy the OAuth flow to Google as the upstream identity provider.


@app.get("/.well-known/oauth-authorization-server")
async def oauth_authorization_server_metadata(request: Request):
    """RFC 8414 OAuth Authorization Server Metadata.

    Tells MCP clients (Claude.AI) where our authorization endpoints are.
    """
    base_url = _get_base_url(request)

    return {
        "issuer": base_url,
        "authorization_endpoint": f"{base_url}/authorize",
        "token_endpoint": f"{base_url}/token",
        "registration_endpoint": f"{base_url}/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["client_secret_post", "none"],
        "scopes_supported": list(OAUTH_SCOPES.keys()),
    }


@app.get("/authorize")
async def oauth_authorize(request: Request):
    """OAuth authorization endpoint - redirects to Google OAuth.

    Claude.AI sends the user here. We redirect to Google's authorize endpoint,
    mapping scopes and preserving PKCE parameters. Google redirects back to
    Claude.AI's callback directly.
    """
    params = dict(request.query_params)

    # Map any non-Google scopes to Google-compatible scopes
    requested_scope = params.get("scope", "")
    google_scopes = _map_to_google_scopes(requested_scope)
    params["scope"] = google_scopes

    # Ensure client_id is set (use ours if not provided)
    if "client_id" not in params or not params["client_id"]:
        params["client_id"] = mcp_settings.MCP_OAUTH_CLIENT_ID

    google_authorize_url = (
        f"{mcp_settings.MCP_OAUTH_AUTHORIZATION_ENDPOINT}?{urlencode(params)}"
    )
    return RedirectResponse(url=google_authorize_url, status_code=302)


@app.post("/token")
async def oauth_token(request: Request):
    """OAuth token endpoint - proxies token exchange to Google.

    Claude.AI sends the authorization code here. We forward it to Google's
    token endpoint, adding our client_secret for the exchange.
    """
    # Parse form data (OAuth token requests use application/x-www-form-urlencoded)
    form_data = await request.form()
    token_params = dict(form_data)

    # Add our client credentials for the token exchange
    token_params["client_id"] = mcp_settings.MCP_OAUTH_CLIENT_ID
    token_params["client_secret"] = mcp_settings.MCP_OAUTH_CLIENT_SECRET

    async with httpx.AsyncClient() as client:
        response = await client.post(
            mcp_settings.MCP_OAUTH_TOKEN_ENDPOINT,
            data=token_params,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    # Return Google's response directly to Claude.AI
    return JSONResponse(
        status_code=response.status_code,
        content=response.json(),
    )


@app.post("/register")
async def oauth_register(request: Request):
    """OAuth Dynamic Client Registration (RFC 7591).

    Returns our Google OAuth client_id so Claude.AI can use it for the
    authorization flow. This is a simplified registration that always
    returns the same client credentials.
    """
    body = await request.json()
    redirect_uris = body.get("redirect_uris", [])
    client_name = body.get("client_name", "MCP Client")

    return JSONResponse(
        status_code=201,
        content={
            "client_id": mcp_settings.MCP_OAUTH_CLIENT_ID,
            "client_name": client_name,
            "redirect_uris": redirect_uris,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
    )


def _get_base_url(request: Request) -> str:
    """Get the external base URL, respecting X-Forwarded-Proto from reverse proxies."""
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("host", request.url.netloc)
    return f"{scheme}://{host}"


def _map_to_google_scopes(requested_scope: str) -> str:
    """Map MCP/custom scopes to Google-compatible OAuth scopes.

    Claude.AI may send scopes like 'claudeai' or our custom 'kb.read kb.write'.
    Google only understands standard OpenID scopes.
    """
    google_scopes = {"openid", "email", "profile"}

    if requested_scope:
        for scope in requested_scope.split():
            # Keep standard scopes, discard custom ones
            if scope in ("openid", "email", "profile"):
                google_scopes.add(scope)

    return " ".join(sorted(google_scopes))


# =============================================================================
# MCP Protocol Endpoint
# =============================================================================


class MCPRequest(BaseModel):
    """MCP JSON-RPC request."""

    jsonrpc: str = "2.0"
    method: str
    params: Optional[dict[str, Any]] = None
    id: Optional[int | str] = None


class MCPResponse(BaseModel):
    """MCP JSON-RPC response."""

    jsonrpc: str = "2.0"
    result: Optional[Any] = None
    error: Optional[dict[str, Any]] = None
    id: Optional[int | str] = None


@app.get("/mcp")
async def mcp_sse_endpoint(request: Request):
    """MCP SSE endpoint for server-initiated messages."""
    from starlette.responses import StreamingResponse

    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    async def event_generator():
        yield "data: {}\n\n"
        while True:
            await asyncio.sleep(30)
            yield ": heartbeat\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/mcp")
async def mcp_endpoint(request: Request, mcp_request: MCPRequest):
    """MCP JSON-RPC endpoint."""
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    method = mcp_request.method
    params = mcp_request.params or {}

    try:
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {"listChanged": False},
                    "resources": {"subscribe": False, "listChanged": False},
                },
                "serverInfo": {
                    "name": "keboola-knowledge-base",
                    "version": "0.1.0",
                },
            }
        elif method == "notifications/initialized":
            return MCPResponse(id=mcp_request.id, result={})
        elif method == "tools/list":
            result = await handle_tools_list(user)
        elif method == "tools/call":
            result = await handle_tools_call(params, user)
        elif method == "resources/list":
            result = {"resources": []}
        elif method == "resources/read":
            return MCPResponse(
                id=mcp_request.id,
                error={"code": -32601, "message": "No resources available"},
            )
        elif method == "ping":
            result = {}
        else:
            return MCPResponse(
                id=mcp_request.id,
                error={"code": -32601, "message": f"Method not found: {method}"},
            )

        return MCPResponse(id=mcp_request.id, result=result)

    except HTTPException as e:
        return MCPResponse(
            id=mcp_request.id,
            error={"code": -32000, "message": e.detail},
        )
    except Exception as e:
        logger.exception(f"Error handling MCP request: {e}")
        return MCPResponse(
            id=mcp_request.id,
            error={"code": -32603, "message": str(e)},
        )


# Root path aliases — some MCP clients (e.g. Claude.ai) may send requests
# to "/" instead of "/mcp" depending on how the URL is registered.
@app.post("/")
async def mcp_root_endpoint(request: Request, mcp_request: MCPRequest):
    """Root path alias for MCP JSON-RPC endpoint."""
    return await mcp_endpoint(request, mcp_request)


@app.get("/")
async def mcp_root_sse_endpoint(request: Request):
    """Root path alias for MCP SSE endpoint."""
    return await mcp_sse_endpoint(request)


async def handle_tools_list(user: dict) -> dict:
    """Handle tools/list MCP method."""
    user_scopes = user.get("scopes", [])
    accessible_tools = get_tools_for_scopes(user_scopes)

    return {
        "tools": [
            {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.inputSchema,
            }
            for tool in accessible_tools
        ]
    }


async def handle_tools_call(params: dict, user: dict) -> dict:
    """Handle tools/call MCP method."""
    tool_name = params.get("name")
    arguments = params.get("arguments", {})

    if not tool_name:
        raise HTTPException(status_code=400, detail="Missing tool name")

    # Check scope access
    user_scopes = user.get("scopes", [])
    required_scopes = TOOL_SCOPE_REQUIREMENTS.get(tool_name, ["kb.read"])

    if not check_scope_access(required_scopes, user_scopes):
        raise HTTPException(
            status_code=403,
            detail=f"Insufficient scope for tool: {tool_name}",
        )

    result = await execute_tool(tool_name, arguments, user)

    return {
        "content": [{"type": r.type, "text": r.text} for r in result],
    }


# =============================================================================
# Main Entry Point
# =============================================================================


def main():
    """Run MCP HTTP server."""
    import uvicorn

    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if mcp_settings.MCP_DEBUG else logging.INFO,
        format='{"time": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "message": "%(message)s"}',
        force=True,
    )

    uvicorn.run(
        "knowledge_base.mcp.server:app",
        host=mcp_settings.MCP_HOST,
        port=mcp_settings.MCP_PORT,
        reload=mcp_settings.MCP_DEBUG,
    )


if __name__ == "__main__":
    main()
