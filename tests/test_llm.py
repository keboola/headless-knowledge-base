"""Tests for the LLM module."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from knowledge_base.rag.llm import BaseLLM, OllamaLLM
from knowledge_base.rag.factory import get_llm, get_provider, get_available_providers
from knowledge_base.rag.exceptions import LLMProviderNotConfiguredError


class TestOllamaLLM:
    """Tests for OllamaLLM."""

    def test_init_defaults(self):
        """Test default initialization."""
        llm = OllamaLLM()
        assert llm.base_url == "http://ollama:11434"
        assert llm.timeout == 120.0

    def test_init_custom_values(self):
        """Test initialization with custom values."""
        llm = OllamaLLM(
            base_url="http://localhost:11434",
            model="custom-model",
            timeout=60.0,
        )
        assert llm.base_url == "http://localhost:11434"
        assert llm.model == "custom-model"
        assert llm.timeout == 60.0

    def test_base_url_trailing_slash_removed(self):
        """Test that trailing slash is removed from base URL."""
        llm = OllamaLLM(base_url="http://localhost:11434/")
        assert llm.base_url == "http://localhost:11434"

    @pytest.mark.asyncio
    async def test_generate_success(self):
        """Test successful text generation."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = MagicMock()
            mock_response.json.return_value = {"response": "Hello, World!"}
            mock_response.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            llm = OllamaLLM()
            result = await llm.generate("Say hello")

            assert result == "Hello, World!"
            mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_json_success(self):
        """Test successful JSON generation."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = MagicMock()
            mock_response.json.return_value = {"response": '{"key": "value"}'}
            mock_response.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            llm = OllamaLLM()
            result = await llm.generate_json("Generate JSON")

            assert result == {"key": "value"}

    @pytest.mark.asyncio
    async def test_generate_json_handles_markdown(self):
        """Test that JSON wrapped in markdown is parsed correctly."""
        with patch("httpx.AsyncClient") as mock_client_class:
            # Simulate LLM response with markdown code block
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "response": '```json\n{"key": "value"}\n```'
            }
            mock_response.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            llm = OllamaLLM()
            result = await llm.generate_json("Generate JSON")

            assert result == {"key": "value"}

    @pytest.mark.asyncio
    async def test_generate_json_invalid_returns_empty(self):
        """Test that invalid JSON returns empty dict."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = MagicMock()
            mock_response.json.return_value = {"response": "not valid json at all"}
            mock_response.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            llm = OllamaLLM()
            result = await llm.generate_json("Generate JSON")

            assert result == {}

    @pytest.mark.asyncio
    async def test_check_health_success(self):
        """Test health check returns True when Ollama is available."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = MagicMock()
            mock_response.status_code = 200

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            llm = OllamaLLM()
            result = await llm.check_health()

            assert result is True

    @pytest.mark.asyncio
    async def test_check_health_failure(self):
        """Test health check returns False when Ollama is unavailable."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=Exception("Connection refused"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            llm = OllamaLLM()
            result = await llm.check_health()

            assert result is False

    @pytest.mark.asyncio
    async def test_list_models_success(self):
        """Test listing available models."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "models": [{"name": "llama3.1:8b"}, {"name": "mistral:7b"}]
            }
            mock_response.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            llm = OllamaLLM()
            result = await llm.list_models()

            assert result == ["llama3.1:8b", "mistral:7b"]

    @pytest.mark.asyncio
    async def test_list_models_failure(self):
        """Test list models returns empty on failure."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=Exception("Error"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            llm = OllamaLLM()
            result = await llm.list_models()

            assert result == []


class TestBaseLLM:
    """Tests for BaseLLM abstract class."""

    def test_cannot_instantiate_directly(self):
        """Test that BaseLLM cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BaseLLM()


class TestLLMFactory:
    """Tests for LLM factory and provider selection."""

    def test_get_available_providers(self):
        """Test that available providers include claude and ollama."""
        providers = get_available_providers()
        assert "claude" in providers
        assert "ollama" in providers

    def test_get_provider_ollama(self):
        """Test getting Ollama provider by name."""
        llm = get_provider("ollama")
        assert llm.provider_name == "ollama"

    def test_get_provider_claude(self):
        """Test getting Claude provider by name."""
        llm = get_provider("claude")
        assert llm.provider_name == "claude"

    def test_get_provider_case_insensitive(self):
        """Test that provider names are case insensitive."""
        llm = get_provider("OLLAMA")
        assert llm.provider_name == "ollama"

    def test_get_provider_unknown_raises(self):
        """Test that unknown provider raises exception."""
        with pytest.raises(LLMProviderNotConfiguredError) as exc_info:
            get_provider("unknown_provider")
        assert "unknown_provider" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_llm_with_explicit_provider(self):
        """Test get_llm with explicit provider parameter."""
        llm = await get_llm(provider="ollama")
        assert llm.provider_name == "ollama"

    @pytest.mark.asyncio
    async def test_get_llm_uses_config_provider(self, monkeypatch):
        """Test that get_llm uses LLM_PROVIDER from config."""
        # Need to patch settings before importing
        with patch("knowledge_base.rag.factory.settings") as mock_settings:
            mock_settings.LLM_PROVIDER = "ollama"
            mock_settings.ANTHROPIC_API_KEY = ""
            mock_settings.OLLAMA_BASE_URL = "http://test:11434"
            mock_settings.OLLAMA_LLM_MODEL = "test-model"

            llm = await get_llm()
            assert llm.provider_name == "ollama"

    @pytest.mark.asyncio
    async def test_get_llm_auto_selects_claude_with_api_key(self):
        """Test that get_llm auto-selects Claude when API key is set."""
        # Patch both factory and claude provider settings
        with patch("knowledge_base.rag.factory.settings") as factory_settings, \
             patch("knowledge_base.rag.providers.claude.settings") as claude_settings:
            factory_settings.LLM_PROVIDER = ""  # Empty for auto-select
            factory_settings.ANTHROPIC_API_KEY = "test-api-key"

            claude_settings.ANTHROPIC_API_KEY = "test-api-key"
            claude_settings.ANTHROPIC_MODEL = "claude-3-5-haiku-20241022"

            llm = await get_llm()
            assert llm.provider_name == "claude"

    @pytest.mark.asyncio
    async def test_get_llm_falls_back_to_ollama(self):
        """Test that get_llm falls back to Ollama when no Claude key."""
        with patch("knowledge_base.rag.factory.settings") as mock_settings:
            mock_settings.LLM_PROVIDER = ""  # Empty for auto-select
            mock_settings.ANTHROPIC_API_KEY = ""  # No Claude key
            mock_settings.OLLAMA_BASE_URL = "http://test:11434"
            mock_settings.OLLAMA_LLM_MODEL = "test-model"

            llm = await get_llm()
            assert llm.provider_name == "ollama"


class TestOllamaLLMProviderInterface:
    """Tests for OllamaLLM provider interface methods."""

    def test_provider_name(self):
        """Test that OllamaLLM returns correct provider name."""
        llm = OllamaLLM()
        assert llm.provider_name == "ollama"

    @pytest.mark.asyncio
    async def test_is_available_with_url(self):
        """Test is_available returns True when URL is set."""
        llm = OllamaLLM(base_url="http://localhost:11434")
        assert await llm.is_available() is True

    @pytest.mark.asyncio
    async def test_is_available_checks_base_url(self):
        """Test is_available checks that base_url is truthy."""
        # OllamaLLM with explicit base_url
        llm = OllamaLLM(base_url="http://localhost:11434")
        assert await llm.is_available() is True
        assert llm.base_url == "http://localhost:11434"
