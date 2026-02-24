"""
OAuth 2.1 Resource Server Implementation

Provides FastAPI middleware for OAuth token validation and user context extraction.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .token_validator import TokenValidator, TokenValidationError
from .metadata import ProtectedResourceMetadata

logger = logging.getLogger(__name__)


def extract_user_context(claims: dict[str, Any]) -> dict[str, Any]:
    """
    Extract user context from validated token claims.

    Args:
        claims: Decoded JWT claims

    Returns:
        User context dictionary with:
        - email: User's email address
        - scopes: List of granted scopes
        - sub: Subject identifier

    Scope logic:
        - All verified Google users get: kb.read
        - Verified @keboola.com users additionally get: kb.write
        - Non-Google tokens: scopes extracted from the 'scope' claim as-is

    Note:
        Google ID tokens don't include a 'scope' claim. For Google OAuth,
        we grant default scopes based on email verification and domain.
    """
    # Extract scopes (space-separated string to list)
    scope_string = claims.get("scope", "")
    scopes = scope_string.split() if scope_string else []

    # For Google OAuth tokens without scope claim, grant default scopes
    # Google tokens have 'iss' = 'https://accounts.google.com' and 'email_verified'
    if not scopes and claims.get("iss") == "https://accounts.google.com":
        email = claims.get("email", "")
        email_verified = claims.get("email_verified", False)

        if email_verified and email:
            # Grant read access to all verified Google users
            scopes = [
                "openid",
                "email",
                "profile",
                "kb.read",
            ]
            logger.info("Google OAuth: granted default scopes for verified user")

            # Grant write access for @keboola.com domain (internal users)
            if email.endswith("@keboola.com"):
                scopes.append("kb.write")
                logger.info("Google OAuth: granted write scope for internal user")

    return {
        "sub": claims.get("sub"),
        "email": claims.get("email", claims.get("sub")),
        "scopes": scopes,
        "claims": claims,
    }


@dataclass
class OAuthResourceServer:
    """
    OAuth 2.1 Resource Server configuration.

    Manages token validation and protected resource metadata.
    """

    resource: str
    authorization_servers: list[str]
    audience: str
    scopes_supported: list[str] = field(default_factory=list)

    # Internal components
    _validator: Optional[TokenValidator] = field(default=None, repr=False)
    _metadata: Optional[ProtectedResourceMetadata] = field(default=None, repr=False)

    def __post_init__(self):
        """Initialize internal components."""
        if self.authorization_servers:
            self._validator = TokenValidator(
                issuer=self.authorization_servers[0],
                audience=self.audience,
            )

        self._metadata = ProtectedResourceMetadata(
            resource=self.resource,
            authorization_servers=self.authorization_servers,
            scopes_supported=self.scopes_supported,
        )

    @property
    def metadata(self) -> ProtectedResourceMetadata:
        """Get protected resource metadata."""
        return self._metadata

    @property
    def validator(self) -> TokenValidator:
        """Get token validator."""
        if not self._validator:
            raise RuntimeError("No authorization server configured")
        return self._validator

    def validate_token(self, token: str) -> dict[str, Any]:
        """Validate access token and return claims."""
        return self.validator.validate(token)

    async def validate_token_async(self, token: str) -> dict[str, Any]:
        """Validate access token asynchronously."""
        return await self.validator.validate_async(token)


class OAuthMiddleware(BaseHTTPMiddleware):
    """
    FastAPI/Starlette middleware for OAuth token validation.

    Validates Bearer tokens in Authorization header and adds
    user context to request.state.
    """

    def __init__(
        self,
        app,
        resource_server: Optional[OAuthResourceServer] = None,
        exclude_paths: Optional[list[str]] = None,
        dev_mode: bool = False,
    ):
        """
        Initialize OAuth middleware.

        Args:
            app: FastAPI/Starlette application
            resource_server: OAuth resource server configuration
            exclude_paths: Paths to exclude from auth (e.g., /health)
            dev_mode: If True, skip validation (for development only)
        """
        super().__init__(app)
        self.resource_server = resource_server
        self.exclude_paths = exclude_paths or [
            "/health",
            "/.well-known/oauth-protected-resource",
            "/callback",
        ]
        self.dev_mode = dev_mode

    def _extract_token(self, request: Request) -> Optional[str]:
        """Extract Bearer token from Authorization header."""
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:]
        return None

    def _should_skip_auth(self, request: Request) -> bool:
        """Check if path should skip authentication."""
        path = request.url.path
        return any(
            path == excluded or path.startswith(f"{excluded}/")
            for excluded in self.exclude_paths
        )

    def _unauthorized_response(self, error: str = "Unauthorized") -> Response:
        """Return 401 Unauthorized response with WWW-Authenticate header."""
        return JSONResponse(
            status_code=401,
            content={"error": "unauthorized", "error_description": error},
            headers={
                "WWW-Authenticate": 'Bearer realm="knowledge-base-mcp", error="invalid_token"'
            },
        )

    def _forbidden_response(self, error: str = "Forbidden") -> Response:
        """Return 403 Forbidden response."""
        return JSONResponse(
            status_code=403,
            content={"error": "insufficient_scope", "error_description": error},
        )

    async def dispatch(
        self, request: Request, call_next: Callable
    ) -> Response:
        """Process request through OAuth validation."""

        # Skip auth for excluded paths
        if self._should_skip_auth(request):
            return await call_next(request)

        # Extract token
        token = self._extract_token(request)
        if not token:
            return self._unauthorized_response("Missing Bearer token")

        # Dev mode: skip validation
        if self.dev_mode:
            request.state.user = {
                "sub": "dev-user",
                "email": "dev@example.com",
                "scopes": ["openid", "kb.read", "kb.write"],
                "claims": {},
            }
            return await call_next(request)

        # Validate token
        if not self.resource_server:
            return self._unauthorized_response("OAuth not configured")

        try:
            claims = await self.resource_server.validate_token_async(token)
            request.state.user = extract_user_context(claims)
            return await call_next(request)
        except TokenValidationError as e:
            logger.warning(f"Token validation failed: {type(e).__name__}")
            return self._unauthorized_response(str(e))
        except Exception as e:
            logger.error(f"Unexpected error during token validation: {type(e).__name__}")
            return self._unauthorized_response("Token validation failed")


def require_scopes(*required_scopes: str):
    """
    Dependency for requiring specific OAuth scopes.

    Usage:
        @app.get("/api/search")
        async def search(user: dict = Depends(require_scopes("kb.read"))):
            ...
    """
    from fastapi import HTTPException, Request

    async def dependency(request: Request) -> dict:
        user = getattr(request.state, "user", None)
        if not user:
            raise HTTPException(status_code=401, detail="Not authenticated")

        user_scopes = user.get("scopes", [])
        has_scope = any(scope in user_scopes for scope in required_scopes)

        if not has_scope:
            raise HTTPException(
                status_code=403,
                detail=f"Required scope: {' or '.join(required_scopes)}",
            )

        return user

    return dependency
