"""Claude LLM via Vertex AI Model Garden.

This provider uses Claude models through Google Cloud's Vertex AI,
which counts towards GCP consumption credits.
"""

import logging
from typing import Any

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

# Default Claude model on Vertex AI
DEFAULT_VERTEX_CLAUDE_MODEL = "claude-sonnet-4@20250514"


class VertexClaudeLLM(BaseLLM):
    """Claude LLM client via Vertex AI Model Garden.

    Uses the Anthropic SDK with Vertex AI authentication.
    This routes requests through GCP and counts towards GCP credits.
    """

    def __init__(
        self,
        project: str | None = None,
        location: str | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
    ):
        """Initialize Vertex AI Claude client.

        Args:
            project: GCP project ID (defaults to settings)
            location: GCP region (defaults to settings.VERTEX_AI_LOCATION)
            model: Claude model ID (defaults to settings.VERTEX_AI_CLAUDE_MODEL)
            max_tokens: Default max tokens for responses
        """
        self.project = project or settings.VERTEX_AI_PROJECT or settings.GCP_PROJECT_ID
        self.location = location or settings.VERTEX_AI_LOCATION
        self.model = model or getattr(settings, 'VERTEX_AI_CLAUDE_MODEL', DEFAULT_VERTEX_CLAUDE_MODEL)
        self.max_tokens = max_tokens
        self._client = None
        self._initialized = False

        if not self.project:
            logger.warning("GCP project not configured for Vertex AI Claude")

    @property
    def provider_name(self) -> str:
        """Return the provider name."""
        return "vertex-claude"

    def _initialize(self):
        """Lazy initialization of Vertex AI Anthropic client."""
        if self._initialized:
            return

        try:
            from anthropic import AnthropicVertex

            self._client = AnthropicVertex(
                project_id=self.project,
                region=self.location,
            )
            self._initialized = True
            logger.info(
                f"Initialized Vertex AI Claude: model={self.model}, "
                f"project={self.project}, location={self.location}"
            )
        except ImportError as e:
            raise ImportError(
                "anthropic package not installed. "
                "Install with: pip install anthropic[vertex]"
            ) from e

    async def is_available(self) -> bool:
        """Check if Vertex AI Claude is configured."""
        return bool(self.project)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((LLMConnectionError, LLMRateLimitError)),
    )
    async def generate(self, prompt: str, **kwargs: Any) -> str:
        """Generate text using Claude via Vertex AI.

        Args:
            prompt: The prompt to send to Claude
            **kwargs: Additional parameters (max_tokens, etc.)

        Returns:
            Generated text response
        """
        if not self.project:
            raise LLMAuthenticationError(
                "GCP project not configured", provider=self.provider_name
            )

        self._initialize()

        try:
            import asyncio

            # anthropic SDK is sync, run in executor
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self._client.messages.create(
                    model=self.model,
                    max_tokens=kwargs.get("max_tokens", self.max_tokens),
                    messages=[{"role": "user", "content": prompt}],
                ),
            )

            # Extract text from response
            text_parts = [
                block.text
                for block in response.content
                if hasattr(block, "text")
            ]
            return "".join(text_parts)

        except Exception as e:
            error_str = str(e).lower()
            if "authentication" in error_str or "permission" in error_str:
                raise LLMAuthenticationError(
                    f"Authentication failed: {e}", provider=self.provider_name
                ) from e
            elif "rate" in error_str or "quota" in error_str:
                raise LLMRateLimitError(
                    f"Rate limit exceeded: {e}", provider=self.provider_name
                ) from e
            else:
                raise LLMConnectionError(
                    f"Request failed: {e}", provider=self.provider_name
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
        """Check if Vertex AI Claude is accessible."""
        if not self.project:
            logger.warning("Vertex Claude health check: No GCP project configured")
            return False

        try:
            self._initialize()
            # Make a minimal request to verify connectivity
            import asyncio

            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self._client.messages.create(
                    model=self.model,
                    max_tokens=10,
                    messages=[{"role": "user", "content": "Hi"}],
                ),
            )
            logger.info("Vertex Claude health check: OK")
            return True
        except Exception as e:
            logger.error(f"Vertex Claude health check failed: {e}")
            return False
