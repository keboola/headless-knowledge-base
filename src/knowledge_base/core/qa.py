"""Core Q&A logic for knowledge base search and answer generation.

Extracted from the Slack bot to be reusable across interfaces (Slack, MCP, API).
"""

import logging

from knowledge_base.rag.factory import get_llm
from knowledge_base.rag.exceptions import LLMError
from knowledge_base.search import HybridRetriever, SearchResult

logger = logging.getLogger(__name__)


async def search_knowledge(query: str, limit: int = 5) -> list[SearchResult]:
    """Search for relevant chunks using Graphiti hybrid search.

    Uses HybridRetriever which delegates to Graphiti's unified search:
    - Semantic similarity (embeddings)
    - BM25 keyword matching
    - Graph relationships

    Returns SearchResult objects with content and metadata.
    """
    logger.info(f"Searching for: '{query[:100]}...'")

    try:
        retriever = HybridRetriever()
        health = await retriever.check_health()
        logger.info(f"Hybrid search health: {health}")

        # Use Graphiti hybrid search
        results = await retriever.search(query, k=limit)
        logger.info(f"Hybrid search returned {len(results)} results")

        # Log first result for debugging
        if results:
            first = results[0]
            logger.info(
                f"First result: chunk_id={first.chunk_id}, "
                f"title={first.page_title}, content_len={len(first.content)}"
            )

        return results

    except Exception as e:
        logger.error(f"Hybrid search FAILED (returning 0 results): {e}", exc_info=True)

    return []


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

    # Build context from chunks (SearchResult has page_title property and content attribute)
    context_parts = []
    for i, chunk in enumerate(chunks, 1):
        context_parts.append(
            f"[Source {i}: {chunk.page_title}]\n{chunk.content[:1000]}"
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

    prompt = f"""You are Keboola's internal knowledge base assistant. Answer questions ONLY based on the provided context documents.

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
- Be concise and helpful. Use bullet points for multiple items.
- If the documents only partially answer the question, share what IS available and note what's missing.
- Do NOT invent tool names, process steps, or policies not mentioned in the documents.

Provide your answer:"""

    try:
        llm = await get_llm()
        logger.info(f"Using LLM provider: {llm.provider_name}")

        # Skip health check - generate() has proper retry logic and error handling
        answer = await llm.generate(prompt)
        return answer.strip()
    except LLMError as e:
        logger.error(f"LLM provider error: {e}")
        return (
            f"I found {len(chunks)} relevant documents but couldn't generate "
            f"an answer at this time. Please try again later."
        )
    except Exception as e:
        logger.error(f"LLM generation failed: {e}")
        return (
            f"I found {len(chunks)} relevant documents but couldn't generate "
            f"an answer at this time. Please try again later."
        )
