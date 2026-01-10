"""Claude (Anthropic) LLM implementation using raw httpx."""

import json
import logging
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from knowledge_base.config import settings
from knowledge_base.rag.exceptions import (
    LLMAuthenticationError,
    LLMConnectionError,
    LLMRateLimitError,
)
from knowledge_base.rag.llm import BaseLLM

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


class ClaudeLLM(BaseLLM):
    """Claude LLM client using the Anthropic API.

    Uses raw httpx for API calls (no SDK dependency).
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 60.0,
        max_tokens: int = 4096,
    ):
        """Initialize Claude LLM client.

        Args:
            api_key: Anthropic API key (defaults to settings.ANTHROPIC_API_KEY)
            model: Model to use (defaults to settings.ANTHROPIC_MODEL)
            timeout: Request timeout in seconds
            max_tokens: Default max tokens for responses
        """
        self.api_key = api_key or settings.ANTHROPIC_API_KEY
        self.model = model or settings.ANTHROPIC_MODEL
        self.timeout = timeout
        self.max_tokens = max_tokens

        if not self.api_key:
            logger.warning("Claude API key not configured")

    @property
    def provider_name(self) -> str:
        """Return the provider name."""
        return "claude"

    async def is_available(self) -> bool:
        """Check if Claude is configured (API key exists)."""
        return bool(self.api_key)

    def _get_headers(self) -> dict[str, str]:
        """Get API request headers."""
        return {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
        }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((LLMConnectionError, LLMRateLimitError)),
    )
    async def generate(self, prompt: str, **kwargs: Any) -> str:
        """Generate text from a prompt using Claude.

        Args:
            prompt: The prompt to send to Claude
            **kwargs: Additional parameters (max_tokens, etc.)

        Returns:
            Generated text response

        Raises:
            LLMAuthenticationError: If API key is invalid
            LLMRateLimitError: If rate limit is exceeded
            LLMConnectionError: If connection fails
        """
        if not self.api_key:
            raise LLMAuthenticationError(
                "API key not configured", provider=self.provider_name
            )

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(
                    ANTHROPIC_API_URL,
                    headers=self._get_headers(),
                    json={
                        "model": self.model,
                        "max_tokens": kwargs.get("max_tokens", self.max_tokens),
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )

                if response.status_code == 401:
                    raise LLMAuthenticationError(
                        "Invalid API key", provider=self.provider_name
                    )
                elif response.status_code == 429:
                    retry_after = response.headers.get("retry-after")
                    raise LLMRateLimitError(
                        "Rate limit exceeded",
                        provider=self.provider_name,
                        retry_after=float(retry_after) if retry_after else None,
                    )

                response.raise_for_status()
                data = response.json()

                # Extract text from Claude response format
                content_blocks = data.get("content", [])
                text_parts = [
                    block.get("text", "")
                    for block in content_blocks
                    if block.get("type") == "text"
                ]
                return "".join(text_parts)

            except httpx.ConnectError as e:
                raise LLMConnectionError(
                    f"Failed to connect: {e}", provider=self.provider_name
                ) from e
            except httpx.TimeoutException as e:
                raise LLMConnectionError(
                    f"Request timed out: {e}", provider=self.provider_name
                ) from e

    async def generate_json(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        """Generate a JSON response from a prompt.

        Args:
            prompt: The prompt to send to Claude
            **kwargs: Additional parameters

        Returns:
            Parsed JSON response, or empty dict on parse failure
        """
        json_prompt = f"""{prompt}

IMPORTANT: Respond ONLY with valid JSON. No markdown, no explanation, just the JSON object."""

        response_text = await self.generate(json_prompt, **kwargs)
        return self._parse_json_response(response_text)

    async def check_health(self) -> bool:
        """Check if Claude API is accessible.

        Note: Unlike Ollama, we can't easily check Claude without making
        a billing API call. We verify the API key is set and make a
        minimal request.
        """
        if not self.api_key:
            logger.warning("Claude health check: No API key configured")
            return False

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    ANTHROPIC_API_URL,
                    headers=self._get_headers(),
                    json={
                        "model": self.model,
                        "max_tokens": 1,
                        "messages": [{"role": "user", "content": "Hi"}],
                    },
                )
                logger.info(f"Claude health check status: {response.status_code}")
                # 200 = success, 400 = bad request but API is reachable
                return response.status_code in (200, 400)
        except httpx.TimeoutException as e:
            logger.error(f"Claude health check timed out: {e}")
            return False
        except httpx.ConnectError as e:
            logger.error(f"Claude health check connection error: {e}")
            return False
        except Exception as e:
            logger.error(f"Claude health check failed: {type(e).__name__}: {e}")
            return False
