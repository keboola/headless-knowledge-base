"""LLM provider factory with registry pattern."""

import logging
from typing import Callable, TypeVar

from knowledge_base.config import settings
from knowledge_base.rag.exceptions import LLMProviderNotConfiguredError

logger = logging.getLogger(__name__)

# Type variable for LLM implementations
T = TypeVar("T")

# Provider registry: maps provider names to factory functions
_PROVIDER_REGISTRY: dict[str, Callable[[], "BaseLLM"]] = {}


def register_provider(name: str) -> Callable[[Callable[[], T]], Callable[[], T]]:
    """Decorator to register an LLM provider factory.

    Usage:
        @register_provider("my_provider")
        def _create_my_provider():
            from knowledge_base.rag.providers.my_provider import MyProviderLLM
            return MyProviderLLM()
    """

    def decorator(factory: Callable[[], T]) -> Callable[[], T]:
        _PROVIDER_REGISTRY[name.lower()] = factory
        logger.debug(f"Registered LLM provider: {name}")
        return factory

    return decorator


def get_available_providers() -> list[str]:
    """Get list of registered provider names."""
    return list(_PROVIDER_REGISTRY.keys())


def get_provider(name: str) -> "BaseLLM":
    """Get an LLM provider instance by name.

    Args:
        name: Provider name ('ollama', 'claude', etc.)

    Returns:
        Configured LLM instance

    Raises:
        LLMProviderNotConfiguredError: If provider is not registered
    """
    name_lower = name.lower()
    if name_lower not in _PROVIDER_REGISTRY:
        available = ", ".join(get_available_providers())
        raise LLMProviderNotConfiguredError(
            f"Unknown provider '{name}'. Available: {available}",
            provider=name,
        )

    return _PROVIDER_REGISTRY[name_lower]()


async def get_llm(provider: str | None = None) -> "BaseLLM":
    """Get an LLM instance (main entry point).

    Uses the configured LLM_PROVIDER. No silent fallback — if the configured
    provider is not available, raises an error immediately.

    Args:
        provider: Specific provider name, or None to use LLM_PROVIDER setting

    Returns:
        Configured LLM instance

    Raises:
        LLMProviderNotConfiguredError: If no provider is configured or available
    """
    provider_name = provider or settings.LLM_PROVIDER
    if not provider_name:
        raise LLMProviderNotConfiguredError(
            "LLM_PROVIDER is not configured. "
            "Set it to 'gemini', 'claude', 'vertex-claude', or 'ollama'.",
            provider="none",
        )

    llm = get_provider(provider_name)
    if not await llm.is_available():
        raise LLMProviderNotConfiguredError(
            f"LLM provider '{provider_name}' is configured but not available. "
            f"Check your credentials and configuration.",
            provider=provider_name,
        )

    logger.info(f"Using LLM provider: {llm.provider_name}")
    return llm


# Import BaseLLM here to avoid circular imports
from knowledge_base.rag.llm import BaseLLM  # noqa: E402


# Register default providers
@register_provider("ollama")
def _create_ollama() -> BaseLLM:
    """Create Ollama LLM instance."""
    from knowledge_base.rag.llm import OllamaLLM

    return OllamaLLM()


@register_provider("claude")
def _create_claude() -> BaseLLM:
    """Create Claude LLM instance."""
    from knowledge_base.rag.providers.claude import ClaudeLLM

    return ClaudeLLM()


@register_provider("gemini")
def _create_gemini() -> BaseLLM:
    """Create Gemini LLM instance."""
    from knowledge_base.rag.providers.gemini import GeminiLLM

    return GeminiLLM()


@register_provider("vertex-claude")
def _create_vertex_claude() -> BaseLLM:
    """Create Claude via Vertex AI instance."""
    from knowledge_base.rag.providers.vertex_claude import VertexClaudeLLM

    return VertexClaudeLLM()
