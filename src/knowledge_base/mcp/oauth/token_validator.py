"""
JWT Token Validator for OAuth 2.1 Resource Server

Validates access tokens issued by the authorization server.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Optional
import logging

import httpx

logger = logging.getLogger(__name__)


class TokenValidationError(Exception):
    """Base exception for token validation errors."""
    pass


class TokenExpiredError(TokenValidationError):
    """Token has expired."""
    pass


class InvalidTokenError(TokenValidationError):
    """Token is invalid (bad signature, format, etc.)."""
    pass


class InvalidIssuerError(TokenValidationError):
    """Token issuer doesn't match expected issuer."""
    pass


class InvalidAudienceError(TokenValidationError):
    """Token audience doesn't match expected audience."""
    pass


@dataclass
class TokenValidator:
    """
    Validates JWT access tokens using JWKS from authorization server.

    Supports:
    - RS256, RS384, RS512 (RSA)
    - ES256, ES384, ES512 (ECDSA)
    - Google OAuth (ID tokens with client_id as audience)
    """

    issuer: str
    audience: str
    jwks_uri: Optional[str] = None
    jwks: dict = field(default_factory=dict)
    _jwks_cache_time: float = field(default=0.0, repr=False)
    _jwks_cache_ttl: int = 3600  # 1 hour
    # Google OAuth specific
    is_google: bool = False
    authorized_party: Optional[str] = None  # For Google: must match client_id

    def __post_init__(self):
        """Initialize JWKS URI from issuer if not provided."""
        if not self.jwks_uri:
            # Google uses a different JWKS endpoint
            if self.issuer == "https://accounts.google.com":
                self.jwks_uri = "https://www.googleapis.com/oauth2/v3/certs"
                self.is_google = True
            else:
                self.jwks_uri = f"{self.issuer.rstrip('/')}/.well-known/jwks.json"

    async def fetch_jwks(self) -> dict:
        """
        Fetch JWKS from authorization server.

        Caches the JWKS for _jwks_cache_ttl seconds.
        """
        now = time.time()
        if self.jwks and (now - self._jwks_cache_time) < self._jwks_cache_ttl:
            return self.jwks

        async with httpx.AsyncClient() as client:
            response = await client.get(self.jwks_uri)
            response.raise_for_status()
            self.jwks = response.json()
            self._jwks_cache_time = now

        return self.jwks

    def validate(self, token: str) -> dict[str, Any]:
        """
        Validate a token synchronously.

        For Google OAuth, handles both:
        - JWT id_tokens (3 parts separated by dots)
        - Opaque access_tokens (validated via Google's tokeninfo endpoint)

        Args:
            token: Token string (JWT or opaque)

        Returns:
            Token claims if valid

        Raises:
            TokenValidationError: If token is invalid
        """
        try:
            import jwt
            from jwt import PyJWKClient
        except ImportError:
            raise TokenValidationError(
                "PyJWT library required for token validation"
            )

        # Check if this is a JWT (3 parts) or opaque token
        parts = token.split(".")
        if len(parts) != 3:
            # Not a JWT - for Google, validate via tokeninfo endpoint
            if self.is_google:
                return self._validate_google_access_token(token)
            raise InvalidTokenError("Invalid JWT format")

        try:
            # Get signing key from JWKS
            jwks_client = PyJWKClient(self.jwks_uri)
            signing_key = jwks_client.get_signing_key_from_jwt(token)

            # Google ID tokens use client_id as audience
            if self.is_google:
                # For Google: audience is the client_id
                claims = jwt.decode(
                    token,
                    signing_key.key,
                    algorithms=["RS256"],
                    issuer=self.issuer,
                    audience=self.audience,  # This is the Google client_id
                    options={
                        "require": ["exp", "iss", "aud", "email"],
                        "verify_exp": True,
                        "verify_iss": True,
                        "verify_aud": True,
                    }
                )

                # Additional Google-specific checks
                # Verify azp (authorized party) if provided
                if self.authorized_party and claims.get("azp"):
                    if claims["azp"] != self.authorized_party:
                        raise InvalidTokenError(
                            f"Invalid authorized party: {claims['azp']}"
                        )

                # Google tokens should have email_verified
                if not claims.get("email_verified", False):
                    logger.warning(f"Google token email not verified: {claims.get('email')}")

                return claims
            else:
                # Standard OAuth 2.0 token validation
                claims = jwt.decode(
                    token,
                    signing_key.key,
                    algorithms=["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"],
                    issuer=self.issuer,
                    audience=self.audience,
                    options={
                        "require": ["exp", "iss", "aud"],
                        "verify_exp": True,
                        "verify_iss": True,
                        "verify_aud": True,
                    }
                )

                return claims

        except jwt.ExpiredSignatureError:
            raise TokenExpiredError("Token has expired")
        except jwt.InvalidIssuerError:
            raise InvalidIssuerError(f"Invalid issuer, expected {self.issuer}")
        except jwt.InvalidAudienceError:
            raise InvalidAudienceError(f"Invalid audience, expected {self.audience}")
        except jwt.InvalidTokenError as e:
            raise InvalidTokenError(f"Invalid token: {e}")
        except Exception as e:
            raise TokenValidationError(f"Token validation failed: {e}")

    def _validate_google_access_token(self, token: str) -> dict[str, Any]:
        """
        Validate a Google opaque access token using tokeninfo endpoint.

        Google access tokens are not JWTs, so we validate them by calling
        Google's tokeninfo endpoint which returns user info if valid.

        Args:
            token: Google access token (opaque string)

        Returns:
            Token claims including email, sub, etc.

        Raises:
            TokenValidationError: If token is invalid
        """
        import httpx

        try:
            # Call Google's tokeninfo endpoint
            response = httpx.get(
                "https://www.googleapis.com/oauth2/v3/tokeninfo",
                params={"access_token": token},
                timeout=10.0
            )

            if response.status_code != 200:
                error_data = response.json() if response.text else {}
                raise InvalidTokenError(
                    f"Google token validation failed: {error_data.get('error_description', 'Unknown error')}"
                )

            claims = response.json()

            # Verify audience matches our client_id
            token_aud = claims.get("aud") or claims.get("azp")
            if token_aud != self.audience:
                raise InvalidAudienceError(
                    f"Invalid audience: expected {self.audience}, got {token_aud}"
                )

            # Check expiration
            exp = claims.get("expires_in")
            if exp is not None and int(exp) <= 0:
                raise TokenExpiredError("Token has expired")

            # Normalize claims to match JWT format
            normalized = {
                "sub": claims.get("sub"),
                "email": claims.get("email"),
                "email_verified": claims.get("email_verified") == "true",
                "aud": token_aud,
                "iss": "https://accounts.google.com",
                "scope": claims.get("scope", ""),
            }

            logger.info(f"Google access token validated for: {normalized.get('email')}")
            return normalized

        except httpx.RequestError as e:
            raise TokenValidationError(f"Failed to validate token with Google: {e}")

    async def validate_async(self, token: str) -> dict[str, Any]:
        """
        Validate a token asynchronously.

        Fetches JWKS if not cached before validation.
        """
        await self.fetch_jwks()
        return self.validate(token)

    def get_claims(self, token: str) -> dict[str, Any]:
        """
        Extract claims from token without full validation.

        WARNING: Only use this for debugging/logging.
        Always use validate() for actual token verification.
        """
        try:
            import jwt
            # Decode without verification
            claims = jwt.decode(
                token,
                options={"verify_signature": False}
            )
            return claims
        except Exception as e:
            raise InvalidTokenError(f"Cannot decode token: {e}")
