"""RAG (Retrieval-Augmented Generation) module."""

from knowledge_base.rag.exceptions import (
    LLMAuthenticationError,
    LLMConnectionError,
    LLMError,
    LLMProviderNotConfiguredError,
    LLMRateLimitError,
    LLMResponseError,
)
from knowledge_base.rag.factory import (
    get_available_providers,
    get_llm,
    get_provider,
    register_provider,
)
from knowledge_base.rag.llm import BaseLLM, OllamaLLM

__all__ = [
    # Base classes
    "BaseLLM",
    "OllamaLLM",
    # Factory functions
    "get_llm",
    "get_provider",
    "get_available_providers",
    "register_provider",
    # Exceptions
    "LLMError",
    "LLMConnectionError",
    "LLMAuthenticationError",
    "LLMRateLimitError",
    "LLMResponseError",
    "LLMProviderNotConfiguredError",
]
