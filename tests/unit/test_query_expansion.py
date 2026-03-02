"""Tests for LLM-based query expansion."""

from unittest.mock import AsyncMock, patch

import pytest

from knowledge_base.core.query_expansion import expand_query


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_llm():
    """Create a mock LLM with an async generate_json method."""
    llm = AsyncMock()
    llm.generate_json = AsyncMock()
    return llm


@pytest.fixture
def patch_get_llm(mock_llm):
    """Patch get_llm() to return the mock LLM."""
    with patch(
        "knowledge_base.core.query_expansion.get_llm",
        new_callable=AsyncMock,
        return_value=mock_llm,
    ) as _mock:
        yield mock_llm


@pytest.fixture
def patch_max_variants():
    """Patch SEARCH_QUERY_EXPANSION_MAX_VARIANTS to 3."""
    with patch(
        "knowledge_base.core.query_expansion.settings"
    ) as mock_settings:
        mock_settings.SEARCH_QUERY_EXPANSION_MAX_VARIANTS = 3
        yield mock_settings


# ---------------------------------------------------------------------------
# Tests: successful expansion
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_successful_expansion(patch_get_llm, patch_max_variants):
    """LLM returns valid JSON with queries including the original."""
    patch_get_llm.generate_json.return_value = {
        "queries": [
            "What teams exist at Keboola?",
            "Keboola departments",
            "organizational structure Keboola",
        ]
    }

    result = await expand_query("What teams exist at Keboola?")

    assert len(result) == 3
    assert result[0] == "What teams exist at Keboola?"
    assert "Keboola departments" in result
    assert "organizational structure Keboola" in result


@pytest.mark.asyncio
async def test_original_query_prepended_when_missing(
    patch_get_llm, patch_max_variants
):
    """If LLM omits the original question, it gets prepended."""
    patch_get_llm.generate_json.return_value = {
        "queries": [
            "Keboola departments",
            "organizational structure Keboola",
            "team list Keboola",
        ]
    }

    result = await expand_query("What teams exist at Keboola?")

    assert result[0] == "What teams exist at Keboola?"
    # Original prepended + first (max_variants - 1) LLM results = 3 total
    assert len(result) == 3


@pytest.mark.asyncio
async def test_original_query_case_insensitive_match(
    patch_get_llm, patch_max_variants
):
    """Original is detected case-insensitively and not duplicated."""
    patch_get_llm.generate_json.return_value = {
        "queries": [
            "what teams exist at keboola?",  # lowercase match
            "Keboola departments",
            "org structure",
        ]
    }

    result = await expand_query("What teams exist at Keboola?")

    # The original (lowercased) is already present, so no prepend
    assert len(result) == 3
    assert result[0].lower() == "what teams exist at keboola?"


# ---------------------------------------------------------------------------
# Tests: max_variants enforcement
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_max_variants_respected(patch_get_llm, patch_max_variants):
    """Queries are truncated to SEARCH_QUERY_EXPANSION_MAX_VARIANTS."""
    patch_get_llm.generate_json.return_value = {
        "queries": [
            "What teams exist at Keboola?",
            "Keboola departments",
            "organizational structure",
            "team list",
            "company org chart",
        ]
    }

    result = await expand_query("What teams exist at Keboola?")

    # max_variants = 3, so only first 3 kept
    assert len(result) == 3


@pytest.mark.asyncio
async def test_truncation_with_prepend(patch_get_llm, patch_max_variants):
    """When original is prepended, total still respects max_variants."""
    patch_get_llm.generate_json.return_value = {
        "queries": [
            "Keboola departments",
            "organizational structure",
            "team list",
            "company org chart",
        ]
    }

    result = await expand_query("What teams exist at Keboola?")

    # Original prepended + (max_variants - 1) = 3
    assert len(result) == 3
    assert result[0] == "What teams exist at Keboola?"


# ---------------------------------------------------------------------------
# Tests: fallback on invalid/empty responses
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_invalid_format_not_a_list(patch_get_llm, patch_max_variants):
    """LLM returns queries as a string instead of a list -> fallback."""
    patch_get_llm.generate_json.return_value = {
        "queries": "just a string, not a list"
    }

    result = await expand_query("How does Keboola work?")

    assert result == ["How does Keboola work?"]


@pytest.mark.asyncio
async def test_invalid_format_missing_key(patch_get_llm, patch_max_variants):
    """LLM returns JSON without a 'queries' key -> fallback."""
    patch_get_llm.generate_json.return_value = {
        "results": ["something"]
    }

    result = await expand_query("How does Keboola work?")

    assert result == ["How does Keboola work?"]


@pytest.mark.asyncio
async def test_empty_queries_list(patch_get_llm, patch_max_variants):
    """LLM returns an empty queries list -> fallback."""
    patch_get_llm.generate_json.return_value = {"queries": []}

    result = await expand_query("How does Keboola work?")

    assert result == ["How does Keboola work?"]


@pytest.mark.asyncio
async def test_queries_with_only_falsy_values(
    patch_get_llm, patch_max_variants
):
    """LLM returns queries containing only empty/None values -> fallback."""
    patch_get_llm.generate_json.return_value = {
        "queries": ["", None, "", 0]
    }

    result = await expand_query("How does Keboola work?")

    assert result == ["How does Keboola work?"]


# ---------------------------------------------------------------------------
# Tests: LLM exception handling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_exception_falls_back(patch_get_llm, patch_max_variants):
    """Any exception from LLM -> fallback to original question."""
    patch_get_llm.generate_json.side_effect = RuntimeError("LLM unavailable")

    result = await expand_query("What is Keboola?")

    assert result == ["What is Keboola?"]


@pytest.mark.asyncio
async def test_get_llm_exception_falls_back(patch_max_variants):
    """Exception during get_llm() itself -> fallback."""
    with patch(
        "knowledge_base.core.query_expansion.get_llm",
        new_callable=AsyncMock,
        side_effect=RuntimeError("No LLM provider configured"),
    ):
        result = await expand_query("What is Keboola?")

    assert result == ["What is Keboola?"]


# ---------------------------------------------------------------------------
# Tests: edge cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_single_variant_returned(patch_get_llm, patch_max_variants):
    """LLM returns only the original question -> valid single-element list."""
    patch_get_llm.generate_json.return_value = {
        "queries": ["What is Keboola?"]
    }

    result = await expand_query("What is Keboola?")

    assert result == ["What is Keboola?"]


@pytest.mark.asyncio
async def test_non_string_queries_converted(
    patch_get_llm, patch_max_variants
):
    """Non-string values in queries list are converted to strings."""
    patch_get_llm.generate_json.return_value = {
        "queries": ["What is Keboola?", 42, True]
    }

    result = await expand_query("What is Keboola?")

    assert all(isinstance(q, str) for q in result)
    assert "42" in result
    assert "True" in result


@pytest.mark.asyncio
async def test_prompt_contains_question_and_max_variants(
    patch_get_llm, patch_max_variants
):
    """Verify the prompt passed to the LLM contains the question and max_variants."""
    patch_get_llm.generate_json.return_value = {
        "queries": ["What is Keboola?"]
    }

    await expand_query("What is Keboola?")

    call_args = patch_get_llm.generate_json.call_args
    prompt = call_args[0][0]
    assert "What is Keboola?" in prompt
    assert "3" in prompt  # max_variants = 3
