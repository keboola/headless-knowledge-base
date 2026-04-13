"""Gemini (Vertex AI) LLM implementation."""

import asyncio
import json
import logging
from typing import Any, AsyncIterator

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


class GeminiLLM(BaseLLM):
    """Gemini LLM client using Google Cloud Vertex AI."""

    def __init__(
        self,
        project: str | None = None,
        location: str | None = None,
        model: str | None = None,
        max_output_tokens: int = 4096,
        temperature: float = 0.1,
    ):
        """Initialize Gemini LLM client.

        Args:
            project: GCP project ID (defaults to settings.VERTEX_AI_PROJECT or GCP_PROJECT_ID)
            location: GCP region (defaults to settings.VERTEX_AI_LOCATION)
            model: Model name (defaults to settings.VERTEX_AI_LLM_MODEL)
            max_output_tokens: Maximum tokens in response
            temperature: Sampling temperature (0.0-1.0)
        """
        self.project = project or settings.VERTEX_AI_PROJECT or settings.GCP_PROJECT_ID
        self.location = location or settings.VERTEX_AI_LOCATION
        self.model_name = model or settings.GEMINI_CONVERSATION_MODEL
        self.max_output_tokens = max_output_tokens
        self.temperature = temperature
        self._model = None
        self._initialized = False

        if not self.project:
            logger.warning("Vertex AI project not configured for Gemini")

    @property
    def provider_name(self) -> str:
        """Return the provider name."""
        return "gemini"

    async def is_available(self) -> bool:
        """Check if Gemini is configured (project ID exists)."""
        return bool(self.project and self.location)

    def _initialize(self):
        """Lazy initialization of Gemini model."""
        if self._initialized:
            return

        try:
            import vertexai
            from vertexai.generative_models import GenerativeModel

            vertexai.init(project=self.project, location=self.location)
            self._model = GenerativeModel(self.model_name)
            self._initialized = True
            logger.info(
                f"Initialized Gemini LLM: model={self.model_name}, "
                f"project={self.project}, location={self.location}"
            )
        except ImportError as e:
            raise ImportError(
                "google-cloud-aiplatform not installed. "
                "Install with: pip install google-cloud-aiplatform"
            ) from e

    def _handle_error(self, error: Exception):
        """Convert Google API errors to LLM exceptions."""
        error_str = str(error).lower()

        if "quota" in error_str or "rate" in error_str or "429" in error_str:
            raise LLMRateLimitError(
                f"Rate limit exceeded: {error}",
                provider=self.provider_name,
            ) from error
        elif "permission" in error_str or "403" in error_str:
            raise LLMAuthenticationError(
                f"Permission denied: {error}",
                provider=self.provider_name,
            ) from error
        elif "timeout" in error_str:
            raise LLMConnectionError(
                f"Request timed out: {error}",
                provider=self.provider_name,
            ) from error
        else:
            raise LLMConnectionError(
                f"API error: {error}",
                provider=self.provider_name,
            ) from error

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((LLMConnectionError, LLMRateLimitError)),
    )
    async def generate(self, prompt: str, **kwargs: Any) -> str:
        """Generate text from a prompt using Gemini.

        Args:
            prompt: The prompt to send to Gemini
            **kwargs: Additional parameters (max_output_tokens, temperature)

        Returns:
            Generated text response

        Raises:
            LLMAuthenticationError: If project is not configured
            LLMRateLimitError: If rate limit is exceeded
            LLMConnectionError: If connection fails
        """
        if not self.project:
            raise LLMAuthenticationError(
                "Vertex AI project not configured", provider=self.provider_name
            )

        self._initialize()

        try:
            from vertexai.generative_models import GenerationConfig

            config = GenerationConfig(
                max_output_tokens=kwargs.get("max_output_tokens", self.max_output_tokens),
                temperature=kwargs.get("temperature", self.temperature),
            )

            # Run synchronous generate in executor
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self._model.generate_content(prompt, generation_config=config),
            )

            if response.candidates:
                return response.candidates[0].content.parts[0].text
            return ""

        except Exception as e:
            self._handle_error(e)

    async def generate_stream(
        self, prompt: str, **kwargs: Any
    ) -> AsyncIterator[str]:
        """Stream text chunks from Gemini as they are generated.

        Uses Vertex AI's `generate_content(stream=True)`, which returns a
        synchronous iterator of GenerationResponse.  We bridge it to async
        by reading chunks in a worker thread via ``asyncio.to_thread``.

        Args:
            prompt: Prompt to send to Gemini
            **kwargs: Additional generation parameters (max_output_tokens, temperature)

        Yields:
            Text chunks as Gemini emits them

        Raises:
            LLMAuthenticationError: If project is not configured
            LLMRateLimitError: If rate limit is exceeded
            LLMConnectionError: If connection fails
        """
        if not self.project:
            raise LLMAuthenticationError(
                "Vertex AI project not configured", provider=self.provider_name
            )

        self._initialize()

        from vertexai.generative_models import GenerationConfig

        config = GenerationConfig(
            max_output_tokens=kwargs.get("max_output_tokens", self.max_output_tokens),
            temperature=kwargs.get("temperature", self.temperature),
        )

        # Vertex AI's stream iterator is synchronous, so we pump it through
        # a background thread one chunk at a time using a queue.
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        SENTINEL = object()

        def _producer() -> None:
            """Drain the sync iterator into the asyncio queue."""
            try:
                stream = self._model.generate_content(
                    prompt, generation_config=config, stream=True
                )
                for chunk in stream:
                    if not chunk.candidates:
                        continue
                    parts = chunk.candidates[0].content.parts
                    if not parts:
                        continue
                    text = parts[0].text
                    if text:
                        loop.call_soon_threadsafe(queue.put_nowait, text)
            except Exception as e:  # noqa: BLE001 -- propagate through queue
                loop.call_soon_threadsafe(queue.put_nowait, e)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, SENTINEL)

        producer_task = asyncio.create_task(asyncio.to_thread(_producer))

        try:
            while True:
                item = await queue.get()
                if item is SENTINEL:
                    return
                if isinstance(item, Exception):
                    self._handle_error(item)
                    return
                yield item
        finally:
            # Make sure the producer thread finishes even if consumer aborts
            try:
                await producer_task
            except Exception:  # noqa: BLE001
                pass

    async def generate_json(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        """Generate a JSON response from a prompt.

        Args:
            prompt: The prompt to send to Gemini
            **kwargs: Additional parameters

        Returns:
            Parsed JSON response, or empty dict on parse failure
        """
        json_prompt = f"""{prompt}

IMPORTANT: Respond ONLY with valid JSON. No markdown, no explanation, just the JSON object."""

        response_text = await self.generate(json_prompt, **kwargs)
        return self._parse_json_response(response_text)

    async def check_health(self) -> bool:
        """Check if Gemini API is accessible."""
        if not self.project:
            logger.warning("Gemini health check: No project configured")
            return False

        try:
            self._initialize()

            from vertexai.generative_models import GenerationConfig

            config = GenerationConfig(max_output_tokens=1, temperature=0.0)

            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self._model.generate_content("Hi", generation_config=config),
            )

            return bool(response.candidates)

        except Exception as e:
            logger.error(f"Gemini health check failed: {type(e).__name__}: {e}")
            return False
