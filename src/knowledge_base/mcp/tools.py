"""MCP tool definitions and execution dispatcher for Knowledge Base."""

import json
import logging
import uuid
from datetime import datetime
from typing import Any
from urllib.parse import quote

from mcp.types import TextContent, Tool

from knowledge_base.mcp.config import TOOL_SCOPE_REQUIREMENTS, check_scope_access

logger = logging.getLogger(__name__)


# =============================================================================
# Tool Definitions
# =============================================================================

TOOLS = [
    Tool(
        name="ask_question",
        description=(
            "Ask a question and get an answer with sources from the Keboola knowledge base. "
            "The answer is generated using RAG (retrieval-augmented generation) from indexed "
            "Confluence pages, quick facts, and ingested documents."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question to ask the knowledge base",
                },
                "conversation_history": {
                    "type": "array",
                    "description": "Optional previous messages for context continuity",
                    "items": {
                        "type": "object",
                        "properties": {
                            "role": {"type": "string", "enum": ["user", "assistant"]},
                            "content": {"type": "string"},
                        },
                        "required": ["role", "content"],
                    },
                },
            },
            "required": ["question"],
        },
    ),
    Tool(
        name="search_knowledge",
        description=(
            "Search the Keboola knowledge base for documents matching a query. "
            "Returns ranked results with titles, content snippets, scores, and Confluence URLs. "
            "Uses hybrid search combining semantic similarity, keyword matching, and graph relationships."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results to return (1-20, default 5)",
                    "minimum": 1,
                    "maximum": 20,
                    "default": 5,
                },
                "filters": {
                    "type": "object",
                    "description": "Optional filters to narrow results",
                    "properties": {
                        "space_key": {
                            "type": "string",
                            "description": "Filter by Confluence space key",
                        },
                        "doc_type": {
                            "type": "string",
                            "description": "Filter by document type (e.g., webpage, pdf, quick_fact)",
                        },
                        "topics": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Filter by topics (any match)",
                        },
                        "updated_after": {
                            "type": "string",
                            "description": "Filter by update date (ISO format)",
                        },
                    },
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="create_knowledge",
        description=(
            "Create a quick knowledge fact in the Keboola knowledge base. "
            "The fact is indexed directly into Graphiti (Neo4j knowledge graph) "
            "and becomes immediately searchable."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The knowledge content to save",
                },
                "topics": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional topic tags for the knowledge",
                },
            },
            "required": ["content"],
        },
    ),
    Tool(
        name="ingest_document",
        description=(
            "Ingest an external document into the Keboola knowledge base. "
            "Supports web pages (HTML), PDFs, Google Docs (public/link-shared), "
            "and Notion pages (public). The document is chunked and indexed into Graphiti."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL of the document to ingest",
                },
                "title": {
                    "type": "string",
                    "description": "Optional title override for the document",
                },
            },
            "required": ["url"],
        },
    ),
    Tool(
        name="submit_feedback",
        description=(
            "Submit feedback on a knowledge base chunk. This affects the chunk's "
            "quality score: 'helpful' increases it, while 'outdated', 'incorrect', "
            "and 'confusing' decrease it. Low-scoring chunks are eventually archived."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "chunk_id": {
                    "type": "string",
                    "description": "The ID of the chunk to give feedback on",
                },
                "feedback_type": {
                    "type": "string",
                    "enum": ["helpful", "outdated", "incorrect", "confusing"],
                    "description": "Type of feedback",
                },
                "details": {
                    "type": "string",
                    "description": "Optional details or correction suggestions",
                },
            },
            "required": ["chunk_id", "feedback_type"],
        },
    ),
    Tool(
        name="check_health",
        description=(
            "Check the health of the Keboola knowledge base system. "
            "Returns status of Neo4j graph database, LLM provider, and search subsystem."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
]


def get_tools_for_scopes(user_scopes: list[str]) -> list[Tool]:
    """Return tools accessible to the user based on their scopes."""
    accessible = []
    for tool in TOOLS:
        required = TOOL_SCOPE_REQUIREMENTS.get(tool.name, ["kb.read"])
        if check_scope_access(required, user_scopes):
            accessible.append(tool)
    return accessible


# =============================================================================
# Tool Execution
# =============================================================================


async def execute_tool(
    tool_name: str,
    arguments: dict[str, Any],
    user: dict[str, Any],
) -> list[TextContent]:
    """Execute a tool and return results as TextContent list."""
    from knowledge_base.db.database import init_db
    await init_db()

    logger.info(f"Executing tool: {tool_name}, user: {user.get('sub', 'unknown')}")

    try:
        if tool_name == "ask_question":
            return await _execute_ask_question(arguments, user)
        elif tool_name == "search_knowledge":
            return await _execute_search_knowledge(arguments, user)
        elif tool_name == "create_knowledge":
            return await _execute_create_knowledge(arguments, user)
        elif tool_name == "ingest_document":
            return await _execute_ingest_document(arguments, user)
        elif tool_name == "submit_feedback":
            return await _execute_submit_feedback(arguments, user)
        elif tool_name == "check_health":
            return await _execute_check_health(arguments, user)
        else:
            return [TextContent(type="text", text=f"Unknown tool: {tool_name}")]
    except Exception as e:
        logger.error(f"Tool execution failed: {tool_name}: {e}", exc_info=True)
        return [TextContent(type="text", text=f"Error executing {tool_name}: {str(e)}")]


async def _execute_ask_question(
    arguments: dict[str, Any],
    user: dict[str, Any],
) -> list[TextContent]:
    """Execute ask_question tool."""
    from knowledge_base.core.qa import generate_answer, search_with_expansion

    question = arguments["question"]
    conversation_history = arguments.get("conversation_history")

    # Search for relevant chunks with query expansion
    chunks = await search_with_expansion(question)

    # Generate answer
    answer = await generate_answer(question, chunks, conversation_history)

    # Build sources section (skip empty, deduplicate)
    sources = []
    seen_titles = set()
    for chunk in chunks[:5]:
        metadata = chunk.metadata if hasattr(chunk, "metadata") else {}
        url = metadata.get("url", "")
        title = chunk.page_title if hasattr(chunk, "page_title") else ""
        if not title and not url:
            continue
        label = title or url
        if label in seen_titles:
            continue
        seen_titles.add(label)
        # For Quick Facts, show who provided and who approved
        doc_type = metadata.get("doc_type", "")
        reviewer = metadata.get("reviewed_by", "")
        suffix = f" (approved by {reviewer})" if doc_type == "quick_fact" and reviewer else ""
        if url and title:
            sources.append(f"- [{title}]({url}){suffix}")
        elif url:
            sources.append(f"- {url}{suffix}")
        else:
            sources.append(f"- {title}{suffix}")

    result = answer
    if sources:
        result += "\n\nSources:\n" + "\n".join(sources)

    return [TextContent(type="text", text=result)]


async def _execute_search_knowledge(
    arguments: dict[str, Any],
    user: dict[str, Any],
) -> list[TextContent]:
    """Execute search_knowledge tool."""
    from knowledge_base.core.qa import search_knowledge

    query = arguments["query"]
    top_k = arguments.get("top_k", 5)
    filters = arguments.get("filters")

    # Search
    results = await search_knowledge(query, limit=top_k * 2 if filters else top_k)

    # Apply filters if present
    if filters:
        results = _apply_filters(results, filters)

    # Limit to requested count
    results = results[:top_k]

    if not results:
        return [TextContent(type="text", text=f"No results found for: {query}")]

    # Format results
    lines = [f"Found {len(results)} results for: {query}\n"]
    for i, r in enumerate(results, 1):
        metadata = r.metadata if hasattr(r, "metadata") else {}
        url = metadata.get("url", "")
        title = r.page_title if hasattr(r, "page_title") else ""
        content_preview = r.content[:200] + "..." if len(r.content) > 200 else r.content
        if not content_preview.strip():
            content_preview = "(No content available)"
        score = f"{r.score:.3f}" if hasattr(r, "score") else "N/A"

        lines.append(f"### {i}. {title}")
        lines.append(f"**Score:** {score} | **Chunk ID:** {r.chunk_id}")
        if url:
            lines.append(f"**URL:** {url}")
        lines.append(f"\n{content_preview}\n")

    return [TextContent(type="text", text="\n".join(lines))]


def _apply_filters(results: list, filters: dict) -> list:
    """Apply metadata filters to search results."""
    filtered = []
    for r in results:
        metadata = r.metadata if hasattr(r, "metadata") else {}

        if "space_key" in filters and metadata.get("space_key") != filters["space_key"]:
            continue
        if "doc_type" in filters and metadata.get("doc_type") != filters["doc_type"]:
            continue
        if "topics" in filters:
            result_topics = metadata.get("topics", [])
            if isinstance(result_topics, str):
                try:
                    result_topics = json.loads(result_topics)
                except (json.JSONDecodeError, TypeError):
                    result_topics = [result_topics]
            if not any(t in result_topics for t in filters["topics"]):
                continue
        if "updated_after" in filters:
            updated_at = metadata.get("updated_at", "")
            if updated_at and updated_at < filters["updated_after"]:
                continue

        filtered.append(r)
    return filtered


async def _execute_create_knowledge(
    arguments: dict[str, Any],
    user: dict[str, Any],
) -> list[TextContent]:
    """Execute create_knowledge tool."""
    from knowledge_base.config import settings
    from knowledge_base.graph.graphiti_indexer import GraphitiIndexer
    from knowledge_base.vectorstore.indexer import ChunkData

    content = arguments["content"]
    topics = arguments.get("topics", [])
    user_email = user.get("email", "mcp-user")

    # Create unique IDs
    page_id = f"mcp_{uuid.uuid4().hex[:16]}"
    chunk_id = f"{page_id}_0"
    now = datetime.utcnow()

    chunk_data = ChunkData(
        chunk_id=chunk_id,
        content=content,
        page_id=page_id,
        page_title=f"Quick Fact by {user_email}",
        chunk_index=0,
        space_key="MCP",
        url=f"mcp://user/{quote(user_email, safe='')}",
        author=user_email,
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
        chunk_type="text",
        parent_headers="[]",
        quality_score=100.0,
        access_count=0,
        feedback_count=0,
        owner=user_email,
        reviewed_by="",
        reviewed_at="",
        classification="internal",
        doc_type="quick_fact",
        topics=json.dumps(topics) if topics else "[]",
        audience="[]",
        complexity="",
        summary=content[:200] if len(content) > 200 else content,
    )

    governance_info = None

    if settings.GOVERNANCE_ENABLED:
        from knowledge_base.governance.risk_classifier import RiskClassifier, IntakeRequest
        from knowledge_base.governance.approval_engine import ApprovalEngine

        classifier = RiskClassifier()
        assessment = await classifier.classify(IntakeRequest(
            author_email=user_email,  # OAuth-verified email
            intake_path="mcp_create",
            content=content,
            chunk_count=1,
            content_length=len(content),
        ))

        chunk_data.governance_status = assessment.governance_status
        chunk_data.governance_risk_score = assessment.score
        chunk_data.governance_risk_tier = assessment.tier

        indexer = GraphitiIndexer()
        await indexer.index_single_chunk(chunk_data)

        engine = ApprovalEngine()
        result = await engine.submit([chunk_data], assessment, user_email, "mcp_create")

        governance_info = {
            "governance_status": result.status,
            "risk_score": assessment.score,
            "risk_tier": assessment.tier,
        }
        if result.revert_deadline:
            governance_info["revert_deadline"] = result.revert_deadline.isoformat()
    else:
        indexer = GraphitiIndexer()
        await indexer.index_single_chunk(chunk_data)

    logger.info(f"Created knowledge via MCP: {chunk_id} by {user_email}")

    response_text = f"Knowledge saved successfully.\n\n**Chunk ID:** {chunk_id}\n**Content:** {content[:200]}"
    if governance_info:
        response_text += (
            f"\n\n**Governance:** {governance_info['governance_status']}"
            f" (risk: {governance_info['risk_tier']}, score: {governance_info['risk_score']:.0f})"
        )

    return [TextContent(
        type="text",
        text=response_text,
    )]


async def _execute_ingest_document(
    arguments: dict[str, Any],
    user: dict[str, Any],
) -> list[TextContent]:
    """Execute ingest_document tool."""
    from knowledge_base.slack.ingest_doc import get_ingester

    url = arguments["url"]
    user_email = user.get("email", "mcp-user")

    ingester = get_ingester()
    result = await ingester.ingest_url(
        url=url,
        created_by=user_email,
        channel_id="mcp",
        intake_path="mcp_ingest",
    )

    if result["status"] == "success":
        response_text = (
            f"Document ingested successfully.\n\n"
            f"**Title:** {result['title']}\n"
            f"**Source type:** {result['source_type']}\n"
            f"**Chunks created:** {result['chunks_created']}\n"
            f"**Page ID:** {result['page_id']}"
        )
        # Include governance info if present
        gov_status = result.get("governance_status")
        if gov_status:
            response_text += (
                f"\n\n**Governance:** {gov_status}"
                f" (risk: {result.get('risk_tier', 'N/A')}"
                f", score: {result.get('risk_score', 0):.0f})"
            )

        return [TextContent(
            type="text",
            text=response_text,
        )]
    else:
        return [TextContent(
            type="text",
            text=f"Failed to ingest document: {result.get('error', 'Unknown error')}",
        )]


async def _execute_submit_feedback(
    arguments: dict[str, Any],
    user: dict[str, Any],
) -> list[TextContent]:
    """Execute submit_feedback tool."""
    from knowledge_base.lifecycle.feedback import submit_feedback

    chunk_id = arguments["chunk_id"]
    feedback_type = arguments["feedback_type"]
    details = arguments.get("details")
    user_email = user.get("email", "mcp-user")

    feedback = await submit_feedback(
        chunk_id=chunk_id,
        slack_user_id=f"mcp:{user_email}",
        slack_username=user_email,
        feedback_type=feedback_type,
        comment=details,
    )

    return [TextContent(
        type="text",
        text=(
            f"Feedback submitted.\n\n"
            f"**Chunk ID:** {chunk_id}\n"
            f"**Feedback type:** {feedback_type}\n"
            f"**Feedback ID:** {feedback.id}"
        ),
    )]


async def _execute_check_health(
    arguments: dict[str, Any],
    user: dict[str, Any],
) -> list[TextContent]:
    """Execute check_health tool."""
    from knowledge_base.search import HybridRetriever

    retriever = HybridRetriever()
    health = await retriever.check_health()

    status = "healthy" if health.get("graphiti_healthy") else "degraded"

    return [TextContent(
        type="text",
        text=(
            f"Knowledge Base Health: **{status}**\n\n"
            f"- Graphiti enabled: {health.get('graphiti_enabled', False)}\n"
            f"- Graphiti healthy: {health.get('graphiti_healthy', False)}\n"
            f"- Backend: {health.get('backend', 'unknown')}"
        ),
    )]
