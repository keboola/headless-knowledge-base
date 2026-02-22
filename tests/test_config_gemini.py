"""Tests for Gemini LLM configuration settings."""

import os
from unittest.mock import patch

import pytest

from knowledge_base.config import Settings


class TestGeminiConfig:
    """Tests for Gemini-related configuration settings."""

    def test_llm_provider_default_is_gemini(self):
        """Default LLM_PROVIDER should be 'gemini'."""
        with patch.dict(os.environ, {}, clear=True):
            s = Settings(_env_file=None)
            assert s.LLM_PROVIDER == "gemini"

    def test_gemini_intake_model_default(self):
        """Default GEMINI_INTAKE_MODEL should be gemini-2.5-flash."""
        with patch.dict(os.environ, {}, clear=True):
            s = Settings(_env_file=None)
            assert s.GEMINI_INTAKE_MODEL == "gemini-2.5-flash"

    def test_gemini_conversation_model_default(self):
        """Default GEMINI_CONVERSATION_MODEL should be gemini-2.5-flash."""
        with patch.dict(os.environ, {}, clear=True):
            s = Settings(_env_file=None)
            assert s.GEMINI_CONVERSATION_MODEL == "gemini-2.5-flash"

    def test_vertex_ai_llm_model_backward_compat_intake(self):
        """Setting VERTEX_AI_LLM_MODEL should populate GEMINI_INTAKE_MODEL."""
        with patch.dict(os.environ, {"VERTEX_AI_LLM_MODEL": "gemini-2.0-flash"}, clear=True):
            s = Settings(_env_file=None)
            assert s.GEMINI_INTAKE_MODEL == "gemini-2.0-flash"

    def test_vertex_ai_llm_model_backward_compat_conversation(self):
        """Setting VERTEX_AI_LLM_MODEL should populate GEMINI_CONVERSATION_MODEL."""
        with patch.dict(os.environ, {"VERTEX_AI_LLM_MODEL": "gemini-2.0-flash"}, clear=True):
            s = Settings(_env_file=None)
            assert s.GEMINI_CONVERSATION_MODEL == "gemini-2.0-flash"

    def test_explicit_intake_model_overrides_vertex_ai(self):
        """Explicit GEMINI_INTAKE_MODEL should win over VERTEX_AI_LLM_MODEL."""
        with patch.dict(os.environ, {
            "VERTEX_AI_LLM_MODEL": "gemini-2.0-flash",
            "GEMINI_INTAKE_MODEL": "gemini-2.5-flash",
        }, clear=True):
            s = Settings(_env_file=None)
            assert s.GEMINI_INTAKE_MODEL == "gemini-2.5-flash"

    def test_explicit_conversation_model_overrides_vertex_ai(self):
        """Explicit GEMINI_CONVERSATION_MODEL should win over VERTEX_AI_LLM_MODEL."""
        with patch.dict(os.environ, {
            "VERTEX_AI_LLM_MODEL": "gemini-2.0-flash",
            "GEMINI_CONVERSATION_MODEL": "gemini-2.5-pro",
        }, clear=True):
            s = Settings(_env_file=None)
            assert s.GEMINI_CONVERSATION_MODEL == "gemini-2.5-pro"

    def test_different_intake_and_conversation_models(self):
        """User can set different models for intake and conversation."""
        with patch.dict(os.environ, {
            "GEMINI_INTAKE_MODEL": "gemini-2.5-flash",
            "GEMINI_CONVERSATION_MODEL": "gemini-2.5-pro",
        }, clear=True):
            s = Settings(_env_file=None)
            assert s.GEMINI_INTAKE_MODEL == "gemini-2.5-flash"
            assert s.GEMINI_CONVERSATION_MODEL == "gemini-2.5-pro"

    def test_llm_provider_configurable(self):
        """User can override LLM_PROVIDER to any supported value."""
        with patch.dict(os.environ, {"LLM_PROVIDER": "claude"}, clear=True):
            s = Settings(_env_file=None)
            assert s.LLM_PROVIDER == "claude"
