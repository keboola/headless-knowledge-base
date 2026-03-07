"""Core Q&A logic for knowledge base search and answer generation.

Extracted from the Slack bot to be reusable across interfaces (Slack, MCP, API).
"""

import asyncio
import logging

from knowledge_base.config import settings
from knowledge_base.rag.factory import get_llm
from knowledge_base.rag.exceptions import LLMError
from knowledge_base.search import HybridRetriever, SearchResult

logger = logging.getLogger(__name__)


async def search_knowledge(query: str, limit: int | None = None) -> list[SearchResult]:
    """Search for relevant chunks using Graphiti hybrid search.

    Uses HybridRetriever which delegates to Graphiti's unified search:
    - Semantic similarity (embeddings)
    - BM25 keyword matching
    - Graph relationships

    Returns SearchResult objects with content and metadata.
    """
    if limit is None:
        limit = settings.SEARCH_DEFAULT_LIMIT

    logger.info("Searching for: '%s...' (limit=%d)", query[:100], limit)

    try:
        retriever = HybridRetriever()
        health = await retriever.check_health()
        logger.info("Hybrid search health: %s", health)

        # Use Graphiti hybrid search
        results = await retriever.search(query, k=limit)
        logger.info("Hybrid search returned %d results", len(results))

        # Log first result for debugging
        if results:
            first = results[0]
            logger.info(
                "First result: chunk_id=%s, title=%s, content_len=%d",
                first.chunk_id, first.page_title, len(first.content),
            )

        return results

    except Exception as e:
        logger.error("Hybrid search FAILED (returning 0 results): %s", e, exc_info=True)

    return []


async def search_with_expansion(
    query: str,
    limit: int | None = None,
) -> list[SearchResult]:
    """Search with LLM-based query expansion for better recall.

    Generates 2-3 query variants using the LLM, searches each in parallel,
    and deduplicates results. This mimics what Claude.AI does naturally when
    calling MCP tools multiple times with different phrasings.

    Falls back to single search if expansion is disabled or fails.
    """
    if limit is None:
        limit = settings.SEARCH_DEFAULT_LIMIT

    if not settings.SEARCH_QUERY_EXPANSION_ENABLED:
        return await search_knowledge(query, limit)

    try:
        from knowledge_base.core.query_expansion import expand_query
        queries = await expand_query(query)
        logger.info("Query expansion: '%s' -> %d variants: %s", query[:80], len(queries), queries)
    except Exception as e:
        logger.warning("Query expansion failed, using original query: %s", e)
        return await search_knowledge(query, limit)

    # Search all query variants in parallel
    search_tasks = [search_knowledge(q, limit=limit) for q in queries]
    all_results = await asyncio.gather(*search_tasks, return_exceptions=True)

    # Collect successful results
    result_sets = []
    for i, result in enumerate(all_results):
        if isinstance(result, Exception):
            logger.warning("Search variant %d failed: %s", i, result)
        else:
            result_sets.append(result)

    if not result_sets:
        logger.error("All search variants failed, returning empty")
        return []

    merged = _deduplicate_results(result_sets, limit=limit)
    logger.info(
        "Query expansion: %d variants -> %d total results -> %d after dedup",
        len(queries), sum(len(r) for r in result_sets), len(merged),
    )
    return merged


def _deduplicate_results(
    result_sets: list[list[SearchResult]],
    limit: int,
) -> list[SearchResult]:
    """Merge results from multiple searches, deduplicate by chunk_id, keep best score."""
    seen: dict[str, SearchResult] = {}
    for results in result_sets:
        for r in results:
            if r.chunk_id not in seen or r.score > seen[r.chunk_id].score:
                seen[r.chunk_id] = r

    merged = sorted(seen.values(), key=lambda x: x.score, reverse=True)
    return merged[:limit]


async def generate_answer(
    question: str,
    chunks: list[SearchResult],
    conversation_history: list[dict[str, str]] | None = None,
) -> str:
    """Generate an answer using LLM with retrieved chunks.

    Args:
        question: The user's question
        chunks: SearchResult objects from Graphiti containing content and metadata
        conversation_history: Previous messages in the conversation thread
    """
    if not chunks:
        return "I couldn't find relevant information in the knowledge base to answer your question."

    content_limit = settings.SEARCH_CHUNK_CONTENT_LIMIT

    # Filter chunks with meaningful content before building LLM context
    valid_chunks = [c for c in chunks if c.content and c.content.strip()]
    if not valid_chunks:
        return "I couldn't find relevant information in the knowledge base to answer your question."

    # Build context from chunks (SearchResult has page_title property and content attribute)
    context_parts = []
    for i, chunk in enumerate(valid_chunks, 1):
        title = chunk.page_title or chunk.url or f"Chunk {chunk.chunk_id}"
        context_parts.append(
            f"[Source {i}: {title}]\n{chunk.content[:content_limit]}"
        )
    context = "\n\n---\n\n".join(context_parts)

    # Build conversation history section
    conversation_section = ""
    if conversation_history:
        history_parts = []
        for msg in conversation_history[-6:]:  # Last 6 messages for context
            role = "User" if msg["role"] == "user" else "Assistant"
            # Truncate long messages in history
            content = msg["content"][:500] + "..." if len(msg["content"]) > 500 else msg["content"]
            history_parts.append(f"{role}: {content}")
        if history_parts:
            conversation_section = f"""
PREVIOUS CONVERSATION:
{chr(10).join(history_parts)}

(Use this context to understand what the user is asking about and provide continuity)
"""

    prompt = f"""You are Keboola's internal knowledge base assistant. Answer questions based on the provided context documents.

CRITICAL RULES:
- ONLY use information explicitly stated in the context documents below.
- Do NOT make up, assume, or hallucinate any information not in the documents.
- If the context doesn't contain enough information to answer, say so clearly.
- When referencing information, mention which source it came from.
{conversation_section}
CONTEXT DOCUMENTS:
{context}

CURRENT QUESTION: {question}

INSTRUCTIONS:
- Answer based strictly on the context documents above.
- Be thorough and detailed. Include all relevant information from the sources.
- Use bullet points, lists, and structured formatting for clarity.
- If multiple sources contain relevant information, synthesize them into a comprehensive answer.
- If the documents only partially answer the question, share what IS available and note what's missing.
- Do NOT invent tool names, process steps, or policies not mentioned in the documents.

Provide your answer:"""

    try:
        llm = await get_llm()
        logger.info("Using LLM provider: %s", llm.provider_name)

        # Skip health check - generate() has proper retry logic and error handling
        answer = await llm.generate(prompt)
        return answer.strip()
    except LLMError as e:
        logger.error("LLM provider error: %s", e)
        return (
            f"I found {len(chunks)} relevant documents but couldn't generate "
            f"an answer at this time. Please try again later."
        )
    except Exception as e:
        logger.error("LLM generation failed: %s", e)
        return (
            f"I found {len(chunks)} relevant documents but couldn't generate "
            f"an answer at this time. Please try again later."
        )
