"""Tests for MCP OAuth resource server and scope handling."""

from unittest.mock import MagicMock, patch

import pytest

from knowledge_base.mcp.config import check_scope_access
from knowledge_base.mcp.oauth.resource_server import (
    OAuthResourceServer,
    extract_user_context,
)


# ===========================================================================
# extract_user_context
# ===========================================================================


class TestExtractUserContext:
    """Test user context extraction from JWT claims."""

    def test_google_verified_keboola_email_gets_read_and_write(self):
        """Verified @keboola.com Google user should get kb.read + kb.write."""
        claims = {
            "iss": "https://accounts.google.com",
            "sub": "google-uid-123",
            "email": "alice@keboola.com",
            "email_verified": True,
        }
        ctx = extract_user_context(claims)
        assert ctx["email"] == "alice@keboola.com"
        assert ctx["sub"] == "google-uid-123"
        assert "kb.read" in ctx["scopes"]
        assert "kb.write" in ctx["scopes"]
        # Standard OpenID scopes also present
        assert "openid" in ctx["scopes"]
        assert "email" in ctx["scopes"]
        assert "profile" in ctx["scopes"]

    def test_google_verified_external_email_gets_read_only(self):
        """Verified external Google user should get kb.read but NOT kb.write."""
        claims = {
            "iss": "https://accounts.google.com",
            "sub": "google-uid-456",
            "email": "bob@external.com",
            "email_verified": True,
        }
        ctx = extract_user_context(claims)
        assert ctx["email"] == "bob@external.com"
        assert "kb.read" in ctx["scopes"]
        assert "kb.write" not in ctx["scopes"]

    def test_google_unverified_email_gets_no_scopes(self):
        """Unverified Google user should get no application scopes."""
        claims = {
            "iss": "https://accounts.google.com",
            "sub": "google-uid-789",
            "email": "unverified@keboola.com",
            "email_verified": False,
        }
        ctx = extract_user_context(claims)
        assert ctx["scopes"] == []

    def test_google_missing_email_gets_no_scopes(self):
        """Google user without email claim should get no scopes."""
        claims = {
            "iss": "https://accounts.google.com",
            "sub": "google-uid-noemail",
            "email_verified": True,
        }
        ctx = extract_user_context(claims)
        # email is "" which is falsy, so no scopes granted
        assert ctx["scopes"] == []

    def test_non_google_claims_with_scope_string(self):
        """Non-Google token with 'scope' claim should parse scopes from the string."""
        claims = {
            "iss": "https://some-other-idp.example.com",
            "sub": "user-abc",
            "email": "charlie@other.com",
            "scope": "kb.read kb.write custom_scope",
        }
        ctx = extract_user_context(claims)
        assert ctx["scopes"] == ["kb.read", "kb.write", "custom_scope"]
        assert ctx["email"] == "charlie@other.com"

    def test_non_google_claims_with_empty_scope(self):
        """Non-Google token with empty scope should produce empty scopes list."""
        claims = {
            "iss": "https://another-idp.example.com",
            "sub": "user-xyz",
            "email": "dave@corp.com",
            "scope": "",
        }
        ctx = extract_user_context(claims)
        assert ctx["scopes"] == []

    def test_claims_without_scope_or_google_issuer(self):
        """Token without scope and without Google issuer should produce empty scopes."""
        claims = {
            "iss": "https://custom-auth.example.com",
            "sub": "user-custom",
            "email": "eve@custom.com",
        }
        ctx = extract_user_context(claims)
        assert ctx["scopes"] == []

    def test_sub_fallback_for_email(self):
        """When email claim is missing, email should fall back to sub."""
        claims = {
            "iss": "https://custom-auth.example.com",
            "sub": "user-no-email",
        }
        ctx = extract_user_context(claims)
        assert ctx["email"] == "user-no-email"

    def test_claims_are_preserved(self):
        """Original claims dict should be available in the context."""
        claims = {
            "iss": "https://accounts.google.com",
            "sub": "uid-1",
            "email": "test@keboola.com",
            "email_verified": True,
            "aud": "test-client-id",
            "exp": 9999999999,
        }
        ctx = extract_user_context(claims)
        assert ctx["claims"] is claims


# ===========================================================================
# OAuthResourceServer
# ===========================================================================


class TestOAuthResourceServer:
    """Test OAuthResourceServer initialization and properties."""

    def test_initialization_creates_validator_and_metadata(self):
        """OAuthResourceServer should initialize a validator and metadata."""
        server = OAuthResourceServer(
            resource="https://kb-mcp.example.com",
            authorization_servers=["https://accounts.google.com"],
            audience="test-client-id",
            scopes_supported=["openid", "email", "profile"],
        )
        assert server.resource == "https://kb-mcp.example.com"
        assert server.audience == "test-client-id"
        assert server.metadata is not None
        assert server.validator is not None

    def test_metadata_resource_matches(self):
        """Metadata resource field should match the server resource."""
        server = OAuthResourceServer(
            resource="https://kb-mcp.example.com",
            authorization_servers=["https://accounts.google.com"],
            audience="test-client-id",
        )
        meta_dict = server.metadata.to_dict()
        assert meta_dict["resource"] == "https://kb-mcp.example.com"
        assert "https://accounts.google.com" in meta_dict["authorization_servers"]

    def test_metadata_includes_scopes(self):
        """Metadata should include advertised scopes."""
        server = OAuthResourceServer(
            resource="https://kb-mcp.example.com",
            authorization_servers=["https://accounts.google.com"],
            audience="test-client-id",
            scopes_supported=["openid", "email"],
        )
        meta_dict = server.metadata.to_dict()
        assert "scopes_supported" in meta_dict
        assert meta_dict["scopes_supported"] == ["openid", "email"]

    def test_no_authorization_servers_no_validator(self):
        """Without authorization servers, validator should not be created."""
        server = OAuthResourceServer(
            resource="https://kb-mcp.example.com",
            authorization_servers=[],
            audience="test-client-id",
        )
        with pytest.raises(RuntimeError, match="No authorization server configured"):
            _ = server.validator

    def test_google_issuer_sets_google_jwks_uri(self):
        """Google issuer should configure Google's JWKS endpoint on the validator."""
        server = OAuthResourceServer(
            resource="https://kb-mcp.example.com",
            authorization_servers=["https://accounts.google.com"],
            audience="test-client-id",
        )
        assert server.validator.jwks_uri == "https://www.googleapis.com/oauth2/v3/certs"
        assert server.validator.is_google is True


# ===========================================================================
# check_scope_access
# ===========================================================================


class TestCheckScopeAccess:
    """Test scope access checking logic."""

    def test_matching_scope_grants_access(self):
        """If at least one required scope is in granted scopes, access is granted."""
        assert check_scope_access(["kb.read"], ["kb.read", "kb.write"]) is True

    def test_no_matching_scope_denies_access(self):
        """If no required scope is in granted scopes, access is denied."""
        assert check_scope_access(["kb.write"], ["kb.read"]) is False

    def test_multiple_required_any_match(self):
        """check_scope_access uses ANY (OR) logic for required scopes."""
        assert check_scope_access(["kb.read", "kb.write"], ["kb.read"]) is True

    def test_empty_required_denies(self):
        """Empty required list means no scope matches -> deny."""
        assert check_scope_access([], ["kb.read"]) is False

    def test_empty_granted_denies(self):
        """Empty granted list always denies."""
        assert check_scope_access(["kb.read"], []) is False

    def test_both_empty_denies(self):
        """Both empty -> deny."""
        assert check_scope_access([], []) is False

    def test_exact_single_match(self):
        """Single required scope matching single granted scope."""
        assert check_scope_access(["kb.write"], ["kb.write"]) is True

    def test_openid_scope_does_not_match_kb_read(self):
        """Standard OpenID scopes should not satisfy kb.* requirements."""
        assert check_scope_access(["kb.read"], ["openid", "email", "profile"]) is False
