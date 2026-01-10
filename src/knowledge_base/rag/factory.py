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

    Selection order:
    1. Use specified provider if given
    2. Use LLM_PROVIDER from config if set
    3. Auto-select based on availability (Claude if API key exists, else Ollama)

    Args:
        provider: Specific provider name, or None for automatic selection

    Returns:
        Configured LLM instance

    Raises:
        LLMProviderNotConfiguredError: If no provider is available
    """
    # Use specified or configured provider
    provider_name = provider or settings.LLM_PROVIDER

    if provider_name:
        llm = get_provider(provider_name)
        if await llm.is_available():
            logger.info(f"Using LLM provider: {llm.provider_name}")
            return llm
        logger.warning(f"Configured provider '{provider_name}' not available")

    # Auto-select: try Claude, then Gemini, then Ollama
    if settings.ANTHROPIC_API_KEY:
        llm = get_provider("claude")
        if await llm.is_available():
            logger.info("Auto-selected Claude LLM provider")
            return llm

    # Try Gemini if GCP project is configured
    if settings.VERTEX_AI_PROJECT or settings.GCP_PROJECT_ID:
        llm = get_provider("gemini")
        if await llm.is_available():
            logger.info("Auto-selected Gemini LLM provider")
            return llm

    # Fall back to Ollama
    llm = get_provider("ollama")
    if await llm.is_available():
        logger.info("Auto-selected Ollama LLM provider")
        return llm

    raise LLMProviderNotConfiguredError(
        "No LLM provider is configured or available. "
        "Set ANTHROPIC_API_KEY for Claude, configure GCP project for Gemini, or ensure Ollama is running.",
        provider="none",
    )


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
