"""LLM-based query expansion for improved search recall.

Generates alternative search queries from a user question to capture
information scattered across different phrasings in the knowledge graph.
This mimics what an AI agent (like Claude.AI) does naturally when making
multiple MCP tool calls with different query formulations.
"""

import logging

from knowledge_base.config import settings
from knowledge_base.rag.factory import get_llm

logger = logging.getLogger(__name__)

EXPANSION_PROMPT = """Given a user question about Keboola (a data platform company), generate {max_variants} alternative search queries that would help find all relevant information in a knowledge base.

Focus on:
- Synonyms and related terms (e.g., "departments" -> "teams", "circles", "organizational structure")
- More specific sub-questions that break down the original
- Different phrasings of the same intent
- Technical terms that might be used in documentation

If the question is already very specific (contains exact names, error codes, or precise technical terms), generate fewer variants.

IMPORTANT: Always include the original question as the first query. Return ONLY a JSON object.

Question: {question}

Return JSON: {{"queries": ["original question", "variant 1", "variant 2"]}}"""


async def expand_query(question: str) -> list[str]:
    """Generate search query variants using the LLM.

    Returns a list of 1-3 queries, always starting with the original.
    Falls back to just the original query on any error.

    Args:
        question: The user's original question.

    Returns:
        List of query strings (1 to SEARCH_QUERY_EXPANSION_MAX_VARIANTS).
    """
    max_variants = settings.SEARCH_QUERY_EXPANSION_MAX_VARIANTS

    try:
        llm = await get_llm()
        prompt = EXPANSION_PROMPT.format(
            question=question,
            max_variants=max_variants,
        )

        result = await llm.generate_json(prompt)
        queries = result.get("queries", [])

        if not queries or not isinstance(queries, list):
            logger.warning("Query expansion returned invalid format: %s", result)
            return [question]

        # Ensure original question is first
        queries = [str(q) for q in queries if q][:max_variants]
        if not queries:
            return [question]

        # If original is not in the list, prepend it
        if question.lower() not in [q.lower() for q in queries]:
            queries = [question] + queries[:max_variants - 1]

        logger.info(
            "Query expansion: '%s' -> %d variants",
            question[:80], len(queries),
        )
        return queries

    except Exception as e:
        logger.warning("Query expansion failed (using original): %s", e)
        return [question]
