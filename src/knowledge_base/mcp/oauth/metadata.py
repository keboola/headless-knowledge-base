"""
RFC 9728 OAuth Protected Resource Metadata

Implements the Protected Resource Metadata endpoint for OAuth 2.1 resource servers.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ProtectedResourceMetadata:
    """
    RFC 9728 Protected Resource Metadata.

    Describes the OAuth-protected resource server and its requirements.
    This metadata is served at /.well-known/oauth-protected-resource
    """

    # Required: The resource identifier (typically the server URL)
    resource: str

    # Required: List of authorization servers that can issue tokens
    authorization_servers: list[str]

    # Optional: Supported OAuth scopes
    scopes_supported: list[str] = field(default_factory=list)

    # Optional: Bearer token methods supported
    bearer_methods_supported: list[str] = field(
        default_factory=lambda: ["header"]
    )

    # Optional: Resource documentation URL
    resource_documentation: Optional[str] = None

    # Optional: Additional resource metadata
    resource_signing_alg_values_supported: list[str] = field(
        default_factory=lambda: ["RS256", "ES256"]
    )

    def to_dict(self) -> dict:
        """Serialize metadata to dictionary for JSON response."""
        result = {
            "resource": self.resource,
            "authorization_servers": self.authorization_servers,
        }

        if self.scopes_supported:
            result["scopes_supported"] = self.scopes_supported

        if self.bearer_methods_supported:
            result["bearer_methods_supported"] = self.bearer_methods_supported

        if self.resource_documentation:
            result["resource_documentation"] = self.resource_documentation

        if self.resource_signing_alg_values_supported:
            result["resource_signing_alg_values_supported"] = (
                self.resource_signing_alg_values_supported
            )

        return result

    def to_json(self) -> str:
        """Serialize metadata to JSON string."""
        import json
        return json.dumps(self.to_dict(), indent=2)
