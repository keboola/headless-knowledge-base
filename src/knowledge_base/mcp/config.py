"""MCP server configuration using pydantic-settings."""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class MCPSettings(BaseSettings):
    """MCP server settings loaded from environment variables.

    Required variables (no defaults - fail fast if missing):
        MCP_OAUTH_CLIENT_ID: Google OAuth client ID
        MCP_OAUTH_RESOURCE_IDENTIFIER: Resource server identifier (e.g. "https://kb-mcp.keboola.com")
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # OAuth 2.1 Configuration (Google OAuth)
    MCP_OAUTH_CLIENT_ID: str  # Required - fail fast if missing
    MCP_OAUTH_CLIENT_SECRET: str  # Required - needed for token exchange with Google

    @field_validator("MCP_OAUTH_CLIENT_ID", "MCP_OAUTH_CLIENT_SECRET")
    @classmethod
    def must_be_non_empty(cls, v: str, info) -> str:
        """Ensure OAuth credentials are non-empty strings."""
        if not v or not v.strip():
            raise ValueError(
                f"{info.field_name} must be a non-empty string"
            )
        return v

    MCP_OAUTH_AUTHORIZATION_SERVER: str = "https://accounts.google.com"
    MCP_OAUTH_AUTHORIZATION_ENDPOINT: str = (
        "https://accounts.google.com/o/oauth2/v2/auth"
    )
    MCP_OAUTH_TOKEN_ENDPOINT: str = "https://oauth2.googleapis.com/token"
    MCP_OAUTH_JWKS_URI: str = "https://www.googleapis.com/oauth2/v3/certs"
    MCP_OAUTH_ISSUER: str = "https://accounts.google.com"
    MCP_OAUTH_RESOURCE_IDENTIFIER: str  # Required - e.g. "https://kb-mcp.keboola.com"
    MCP_OAUTH_SCOPES: str = "openid email profile"

    # Rate Limiting
    MCP_RATE_LIMIT_READ_PER_MINUTE: int = 30
    MCP_RATE_LIMIT_WRITE_PER_HOUR: int = 20

    # Server
    MCP_HOST: str = "0.0.0.0"
    MCP_PORT: int = 8080
    MCP_DEV_MODE: bool = False
    MCP_DEBUG: bool = False


# OAuth scope definitions
OAUTH_SCOPES: dict[str, str] = {
    "openid": "OpenID Connect authentication",
    "email": "User email address",
    "profile": "User profile information",
    "kb.read": "Search and query the knowledge base",
    "kb.write": "Create knowledge and submit feedback",
}

# Required scopes per MCP tool
TOOL_SCOPE_REQUIREMENTS: dict[str, list[str]] = {
    "ask_question": ["kb.read"],
    "search_knowledge": ["kb.read"],
    "create_knowledge": ["kb.write"],
    "ingest_document": ["kb.write"],
    "submit_feedback": ["kb.write"],
    "check_health": ["kb.read"],
}

# Tools that perform write operations (subject to stricter rate limits)
WRITE_TOOLS: list[str] = [
    tool
    for tool, scopes in TOOL_SCOPE_REQUIREMENTS.items()
    if "kb.write" in scopes
]

# Rate limit configuration keyed by operation type
RATE_LIMITS: dict[str, dict[str, int]] = {
    "read": {
        "requests": 30,  # Default, overridden by MCPSettings.MCP_RATE_LIMIT_READ_PER_MINUTE
        "window_seconds": 60,
    },
    "write": {
        "requests": 20,  # Default, overridden by MCPSettings.MCP_RATE_LIMIT_WRITE_PER_HOUR
        "window_seconds": 3600,
    },
}


def check_scope_access(required_scopes: list[str], granted_scopes: list[str]) -> bool:
    """Check if any of the required scopes are in the granted scopes.

    Args:
        required_scopes: Scopes required by the tool (at least one must match).
        granted_scopes: Scopes granted to the authenticated user/token.

    Returns:
        True if at least one required scope is present in granted scopes.
    """
    return any(scope in granted_scopes for scope in required_scopes)
