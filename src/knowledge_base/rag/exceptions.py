"""LLM-related exceptions with provider-specific handling."""


class LLMError(Exception):
    """Base exception for LLM operations."""

    def __init__(self, message: str, provider: str = "unknown"):
        self.provider = provider
        super().__init__(f"[{provider}] {message}")


class LLMConnectionError(LLMError):
    """Failed to connect to the LLM service."""

    pass


class LLMRateLimitError(LLMError):
    """Rate limit exceeded (primarily for cloud providers)."""

    def __init__(
        self, message: str, provider: str, retry_after: float | None = None
    ):
        self.retry_after = retry_after
        super().__init__(message, provider)


class LLMAuthenticationError(LLMError):
    """Authentication failed (invalid API key, etc.)."""

    pass


class LLMModelNotFoundError(LLMError):
    """Requested model is not available."""

    def __init__(self, message: str, provider: str, model: str):
        self.model = model
        super().__init__(message, provider)


class LLMResponseError(LLMError):
    """Error parsing or processing LLM response."""

    pass


class LLMProviderNotConfiguredError(LLMError):
    """Provider is not properly configured or not registered."""

    pass
