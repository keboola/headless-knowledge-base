"""MCP HTTP Server with OAuth 2.1 for Knowledge Base.

Provides Streamable HTTP transport for MCP protocol with Google OAuth authentication.
Compatible with Claude.AI remote MCP server integration.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
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


# Initialize resource server
resource_server = OAuthResourceServer(
    resource=mcp_settings.MCP_OAUTH_RESOURCE_IDENTIFIER,
    authorization_servers=[mcp_settings.MCP_OAUTH_AUTHORIZATION_SERVER],
    audience=_get_oauth_audience(),
    scopes_supported=_get_advertised_scopes(),
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global resource_server

    resource_server = OAuthResourceServer(
        resource=mcp_settings.MCP_OAUTH_RESOURCE_IDENTIFIER,
        authorization_servers=[mcp_settings.MCP_OAUTH_AUTHORIZATION_SERVER],
        audience=_get_oauth_audience(),
        scopes_supported=_get_advertised_scopes(),
    )

    logger.info(f"MCP Server started on {mcp_settings.MCP_HOST}:{mcp_settings.MCP_PORT}")
    logger.info(f"OAuth issuer: {mcp_settings.MCP_OAUTH_ISSUER}")
    logger.info(f"OAuth audience: {_get_oauth_audience()}")
    logger.info(f"Dev mode: {mcp_settings.MCP_DEV_MODE}")

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
    allow_origins=["*"],
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
    skip_paths = ["/health", "/.well-known/oauth-protected-resource", "/callback", "/"]
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
        logger.info(f"MCP dev mode: using email {dev_email}")
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
        except Exception as e:
            logger.warning(f"Token validation failed: {type(e).__name__}: {e}")
            return JSONResponse(
                status_code=401,
                content={"error": "invalid_token", "error_description": str(e)},
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
async def oauth_protected_resource_metadata():
    """RFC 9728 Protected Resource Metadata endpoint."""
    if not resource_server:
        raise HTTPException(status_code=503, detail="OAuth not configured")
    return resource_server.metadata.to_dict()


@app.get("/callback")
async def oauth_callback(code: str = None, state: str = None, error: str = None):
    """OAuth authorization code callback."""
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
