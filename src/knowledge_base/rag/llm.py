"""LLM client implementations."""

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from knowledge_base.config import settings

logger = logging.getLogger(__name__)


class BaseLLM(ABC):
    """Base class for LLM implementations."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider name (e.g., 'ollama', 'claude')."""
        pass

    @abstractmethod
    async def generate(self, prompt: str, **kwargs: Any) -> str:
        """Generate text from a prompt."""
        pass

    @abstractmethod
    async def generate_json(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        """Generate a JSON response from a prompt."""
        pass

    @abstractmethod
    async def check_health(self) -> bool:
        """Check if the LLM service is accessible and healthy."""
        pass

    async def is_available(self) -> bool:
        """Lightweight check if provider is configured.

        This checks configuration (e.g., API key exists) without making
        network requests. Override in subclasses as needed.
        """
        return True

    def _parse_json_response(self, response_text: str) -> dict[str, Any]:
        """Parse JSON from LLM response, handling common formatting issues.

        Args:
            response_text: Raw text response from LLM

        Returns:
            Parsed JSON object, or empty dict on parse failure
        """
        try:
            text = response_text.strip()

            # Remove markdown code blocks if present
            if text.startswith("```json"):
                text = text[7:]
            elif text.startswith("```"):
                text = text[3:]

            if text.endswith("```"):
                text = text[:-3]

            text = text.strip()
            return json.loads(text)

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse {self.provider_name} response as JSON: {e}")
            logger.debug(f"Raw response: {response_text}")
            return {}


class OllamaLLM(BaseLLM):
    """Ollama LLM client."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 120.0,
    ):
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.model = model or settings.OLLAMA_LLM_MODEL
        self.timeout = timeout

    @property
    def provider_name(self) -> str:
        """Return the provider name."""
        return "ollama"

    async def is_available(self) -> bool:
        """Check if Ollama is configured (URL exists)."""
        return bool(self.base_url)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def generate(self, prompt: str, **kwargs: Any) -> str:
        """Generate text from a prompt using Ollama."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    **kwargs,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data.get("response", "")

    async def generate_json(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        """Generate a JSON response from a prompt."""
        # Add JSON format instruction to prompt
        json_prompt = f"""{prompt}

IMPORTANT: Respond ONLY with valid JSON. No markdown, no explanation, just the JSON object."""

        response_text = await self.generate(json_prompt, **kwargs)
        return self._parse_json_response(response_text)

    async def check_health(self) -> bool:
        """Check if Ollama is accessible."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                return response.status_code == 200
        except Exception as e:
            logger.error(f"Ollama health check failed: {e}")
            return False

    async def list_models(self) -> list[str]:
        """List available models."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
                data = response.json()
                return [m["name"] for m in data.get("models", [])]
        except Exception as e:
            logger.error(f"Failed to list models: {e}")
            return []
