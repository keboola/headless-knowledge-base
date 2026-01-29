"""Slack bot for knowledge base Q&A with feedback collection."""

import argparse
import asyncio
import json
import logging
import os
import re
from typing import Any

from slack_bolt import App
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient
from sqlalchemy import func, select

from knowledge_base.config import settings
from knowledge_base.db.database import async_session_maker, init_db
from knowledge_base.lifecycle import (
    record_chunk_access,
    submit_feedback,
    process_reaction,
    process_thread_message,
    record_bot_response,
)
from knowledge_base.rag.factory import get_llm
from knowledge_base.rag.exceptions import LLMError
from knowledge_base.search.models import SearchResult
from knowledge_base.slack.modals import (
    build_incorrect_feedback_modal,
    build_outdated_feedback_modal,
    build_confusing_feedback_modal,
)

logger = logging.getLogger(__name__)

# Store pending feedback (message_ts -> chunk_ids used)
pending_feedback: dict[str, list[str]] = {}

# Event deduplication to prevent duplicate responses
_processed_events: set[str] = set()
_MAX_PROCESSED_EVENTS = 1000

# Conversation history cache (thread_ts -> list of messages)
# Each message is {"role": "user"|"assistant", "content": str}
_conversation_cache: dict[str, list[dict[str, str]]] = {}
_MAX_CONVERSATION_CACHE = 500
_MAX_HISTORY_MESSAGES = 10  # Max messages to include in context


def _is_duplicate_event(event: dict) -> bool:
    """Check if we've already processed this event.

    Slack may send duplicate events due to retries or both app_mention
    and message events firing for the same message.
    """
    # Use client_msg_id if available (most reliable), fallback to ts
    event_id = event.get("client_msg_id") or event.get("ts", "")
    if not event_id:
        return False

    if event_id in _processed_events:
        logger.debug(f"Skipping duplicate event: {event_id}")
        return True

    _processed_events.add(event_id)

    # Cleanup old entries to prevent memory growth
    if len(_processed_events) > _MAX_PROCESSED_EVENTS:
        # Remove oldest entries (set doesn't preserve order, so just clear half)
        to_remove = list(_processed_events)[:_MAX_PROCESSED_EVENTS // 2]
        for item in to_remove:
            _processed_events.discard(item)

    return False


def _get_conversation_history(thread_ts: str) -> list[dict[str, str]]:
    """Get conversation history for a thread."""
    return _conversation_cache.get(thread_ts, [])


def _add_to_conversation(thread_ts: str, role: str, content: str) -> None:
    """Add a message to conversation history."""
    if thread_ts not in _conversation_cache:
        _conversation_cache[thread_ts] = []

    _conversation_cache[thread_ts].append({"role": role, "content": content})

    # Trim to max messages
    if len(_conversation_cache[thread_ts]) > _MAX_HISTORY_MESSAGES:
        _conversation_cache[thread_ts] = _conversation_cache[thread_ts][-_MAX_HISTORY_MESSAGES:]

    # Cleanup old conversations if cache is too large
    if len(_conversation_cache) > _MAX_CONVERSATION_CACHE:
        # Remove oldest entries (dict preserves insertion order in Python 3.7+)
        keys_to_remove = list(_conversation_cache.keys())[:_MAX_CONVERSATION_CACHE // 2]
        for key in keys_to_remove:
            _conversation_cache.pop(key, None)


def _register_qa_handlers(app: AsyncApp) -> None:
    """Register Q&A handlers for the async app (HTTP mode)."""

    @app.event("app_mention")
    async def handle_mention(event: dict, say: Any, client: WebClient) -> None:
        """Handle @mentions of the bot."""
        if _is_duplicate_event(event):
            return
        await _handle_question(event, say, client)

    @app.event("message")
    async def handle_dm(event: dict, say: Any, client: WebClient) -> None:
        """Handle direct messages to the bot."""
        # Only respond to DMs (channel type 'im')
        if event.get("channel_type") == "im" and not event.get("bot_id"):
            if _is_duplicate_event(event):
                return
            await _handle_question(event, say, client)

    @app.action(re.compile(r"feedback_(helpful|outdated|incorrect|confusing)_.*"))
    async def handle_feedback(ack: Any, body: dict, client: WebClient) -> None:
        """Handle feedback button clicks."""
        await ack()
        await _handle_feedback_action(body, client)

    @app.event("reaction_added")
    async def handle_reaction(event: dict, client: WebClient) -> None:
        """Handle emoji reactions for behavioral signals."""
        await _handle_reaction_event(event, client)

    @app.event("message")
    async def handle_thread_message(event: dict, say: Any, client: WebClient) -> None:
        """Handle thread messages for behavioral signals."""
        # Skip if no thread_ts (not a thread reply)
        if "thread_ts" not in event:
            return
        # Skip bot messages
        if event.get("bot_id"):
            return
        # Skip the original message that started the thread
        if event.get("ts") == event.get("thread_ts"):
            return
        # Skip if already handled by DM handler
        if event.get("channel_type") == "im":
            return
        # Process for behavioral signals
        await _handle_thread_message_event(event)


def create_async_app() -> AsyncApp:
    """Create and configure the Slack Bolt async app (for HTTP mode)."""
    app = AsyncApp(
        token=settings.SLACK_BOT_TOKEN,
        signing_secret=settings.SLACK_SIGNING_SECRET,
    )

    # Register quick knowledge command first (most important for slash commands)
    try:
        from knowledge_base.slack.quick_knowledge import register_quick_knowledge_handler
        register_quick_knowledge_handler(app)
        logger.info("Quick knowledge command registered")
    except Exception as e:
        logger.warning(f"Failed to register quick knowledge handler: {e}")

    # Register document creation handlers
    try:
        from knowledge_base.slack.doc_creation import register_doc_handlers
        register_doc_handlers(app)
        logger.info("Document creation handlers registered")
    except Exception as e:
        logger.warning(f"Failed to register document handlers: {e}")

    # Register help command
    try:
        from knowledge_base.slack.help_command import register_help_handlers
        register_help_handlers(app)
        logger.info("Help command registered")
    except Exception as e:
        logger.warning(f"Failed to register help handlers: {e}")

    # Register ingest-doc command
    try:
        from knowledge_base.slack.ingest_doc import register_ingest_handler
        register_ingest_handler(app)
        logger.info("Ingest-doc command registered")
    except Exception as e:
        logger.warning(f"Failed to register ingest-doc handlers: {e}")

    # Register admin escalation handlers
    try:
        from knowledge_base.slack.admin_escalation import register_escalation_handlers
        register_escalation_handlers(app)
        logger.info("Admin escalation handlers registered")
    except Exception as e:
        logger.warning(f"Failed to register admin escalation handlers: {e}")

    # Register feedback modal handlers (for negative feedback detail capture)
    try:
        from knowledge_base.slack.feedback_modals import register_feedback_modal_handlers
        register_feedback_modal_handlers(app)
        logger.info("Feedback modal handlers registered")
    except Exception as e:
        logger.warning(f"Failed to register feedback modal handlers: {e}")

    # Register Q&A handlers
    _register_qa_handlers(app)

    return app


def create_app() -> App:
    """Create and configure the Slack Bolt app (for Socket Mode)."""
    app = App(
        token=settings.SLACK_BOT_TOKEN,
        signing_secret=settings.SLACK_SIGNING_SECRET,
    )

    # Register document creation handlers
    try:
        from knowledge_base.slack.doc_creation import register_doc_handlers
        from knowledge_base.slack.quick_knowledge import register_quick_knowledge_handler
        register_doc_handlers(app)
        register_quick_knowledge_handler(app)
        logger.info("Document creation handlers registered")
    except Exception as e:
        logger.warning(f"Failed to register document handlers: {e}")

    # Register help command
    try:
        from knowledge_base.slack.help_command import register_help_handlers
        register_help_handlers(app)
        logger.info("Help command registered")
    except Exception as e:
        logger.warning(f"Failed to register help handlers: {e}")

    # Register ingest-doc command
    try:
        from knowledge_base.slack.ingest_doc import register_ingest_handler
        register_ingest_handler(app)
        logger.info("Ingest-doc command registered")
    except Exception as e:
        logger.warning(f"Failed to register ingest handlers: {e}")

    # Register admin escalation handlers
    try:
        from knowledge_base.slack.admin_escalation import register_escalation_handlers
        register_escalation_handlers(app)
        logger.info("Admin escalation handlers registered")
    except Exception as e:
        logger.warning(f"Failed to register escalation handlers: {e}")

    # Register feedback modal handlers (Phase 10.6)
    try:
        from knowledge_base.slack.feedback_modals import register_feedback_modal_handlers
        register_feedback_modal_handlers(app)
        logger.info("Feedback modal handlers registered")
    except Exception as e:
        logger.warning(f"Failed to register feedback modal handlers: {e}")

    @app.event("app_mention")
    def handle_mention(event: dict, say: Any, client: WebClient) -> None:
        """Handle @mentions of the bot."""
        if _is_duplicate_event(event):
            return
        asyncio.run(_handle_question(event, say, client))

    @app.event("message")
    def handle_dm(event: dict, say: Any, client: WebClient) -> None:
        """Handle direct messages to the bot."""
        # Only respond to DMs (channel type 'im')
        if event.get("channel_type") == "im" and not event.get("bot_id"):
            if _is_duplicate_event(event):
                return
            asyncio.run(_handle_question(event, say, client))

    @app.action(re.compile(r"feedback_(helpful|outdated|incorrect|confusing)_.*"))
    def handle_feedback(ack: Any, body: dict, client: WebClient) -> None:
        """Handle feedback button clicks."""
        ack()
        asyncio.run(_handle_feedback_action(body, client))

    @app.event("reaction_added")
    def handle_reaction(event: dict, client: WebClient) -> None:
        """Handle emoji reactions for behavioral signals (Phase 10.5)."""
        asyncio.run(_handle_reaction_event(event, client))

    @app.event("message")
    def handle_thread_message(event: dict, say: Any, client: WebClient) -> None:
        """Handle thread messages for behavioral signals (Phase 10.5).

        This handles messages in threads that are NOT DMs and NOT the original question.
        """
        # Skip if no thread_ts (not a thread reply)
        if "thread_ts" not in event:
            return

        # Skip bot messages
        if event.get("bot_id"):
            return

        # Skip the original message that started the thread
        if event.get("ts") == event.get("thread_ts"):
            return

        # Skip if already handled by DM handler
        if event.get("channel_type") == "im":
            return

        # Process for behavioral signals
        asyncio.run(_handle_thread_message_event(event))

    return app


async def _search_chunks(query: str, limit: int = 5) -> list[SearchResult]:
    """Search for relevant chunks using Graphiti hybrid search.

    Uses HybridRetriever which delegates to Graphiti's unified search:
    - Semantic similarity (embeddings)
    - BM25 keyword matching
    - Graph relationships

    Returns SearchResult objects with content and metadata.
    """
    logger.info(f"Searching for: '{query[:100]}...'")

    try:
        from knowledge_base.search import HybridRetriever

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
        logger.warning(f"Hybrid search failed: {e}", exc_info=True)

    return []


async def _generate_answer(
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

    prompt = f"""You are Keboola's internal knowledge expert - a knowledgeable colleague who truly understands company processes, policies, and documentation.

Your role is NOT to just search and cite documents. Your role is to THINK and ADVISE based on your knowledge.
{conversation_section}
CONTEXT DOCUMENTS:
{context}

CURRENT QUESTION: {question}

INSTRUCTIONS:
1. UNDERSTAND THE INTENT: What does the user really want to know? Are they looking for:
   - A specific answer or fact?
   - Guidance on how to do something?
   - An overview or explanation of a topic?
   - Help finding the right resource?

2. SYNTHESIZE KNOWLEDGE: Don't just list what documents exist. Extract the actual knowledge and insights:
   - Connect information across multiple sources
   - Identify the key points that answer their question
   - Explain relationships and implications

3. BE CONVERSATIONAL AND HELPFUL:
   - Respond as a knowledgeable colleague would
   - If the question is broad, provide a helpful overview then offer to dive deeper
   - If something is unclear or you need more context, ask a clarifying question
   - Suggest related topics they might find useful

4. WHEN CITING SOURCES:
   - Only cite when providing specific facts or quotes
   - Use natural language: "According to our Tool Administrators guide..." or "Our FAQ mentions..."
   - Don't just list source numbers without context

5. HANDLE UNCERTAINTY:
   - If the documents don't fully answer the question, say what you DO know and what's missing
   - Suggest who they might ask or where else to look

RESPONSE FORMAT:
- Lead with the actual answer or insight, not a list of documents
- Use bullet points for multiple items, but synthesize don't just list
- Keep it concise but complete
- End with a helpful follow-up if appropriate (e.g., "Would you like me to explain any of these in more detail?")

Now provide a thoughtful, knowledge-based response:"""

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


def _create_feedback_buttons(message_ts: str) -> list[dict]:
    """Create feedback button blocks."""
    return [
        {
            "type": "divider"
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "_Was this helpful?_"
            }
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Helpful"},
                    "style": "primary",
                    "action_id": f"feedback_helpful_{message_ts}",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Outdated"},
                    "action_id": f"feedback_outdated_{message_ts}",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Incorrect"},
                    "style": "danger",
                    "action_id": f"feedback_incorrect_{message_ts}",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Confusing"},
                    "action_id": f"feedback_confusing_{message_ts}",
                },
            ],
        },
    ]


async def _handle_question(event: dict, say: Any, client: Any) -> None:
    """Handle a question from a user."""
    import asyncio
    import inspect

    await init_db()

    user_id = event.get("user")
    channel = event.get("channel")
    text = event.get("text", "")
    thread_ts = event.get("thread_ts") or event.get("ts")

    # Remove bot mention from text
    text = re.sub(r"<@[A-Z0-9]+>", "", text).strip()

    # Check for /create-knowledge command in text (fallback for when slash command isn't configured)
    if text.startswith("/create-knowledge"):
        # Extract the content after the command
        content = re.sub(r"^/create-knowledge\s*", "", text).strip()
        # Handle duplicate command prefix (user typed it twice)
        content = re.sub(r"^/create-knowledge\s*", "", content).strip()

        if content:
            # Process as knowledge creation
            from knowledge_base.slack.quick_knowledge import handle_create_knowledge
            # Build a fake command object
            fake_command = {
                "text": content,
                "user_id": user_id,
                "user_name": user_id,  # Will be looked up
                "channel_id": channel,
            }
            # Create a no-op ack function
            async def noop_ack():
                pass
            await handle_create_knowledge(noop_ack, fake_command, client)
            return
        else:
            await say("Please provide the information you want to save. Usage: `/create-knowledge <fact>`", thread_ts=thread_ts)
            return

    # Helper to handle both sync and async say/client calls
    async def async_call(func, *args, **kwargs):
        result = func(*args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    if not text:
        await async_call(say, "Please ask a question!", thread_ts=thread_ts)
        return

    # Get user info
    try:
        user_info = await async_call(client.users_info, user=user_id)
        username = user_info["user"]["name"]
    except Exception:
        username = user_id

    # Send "thinking" message
    thinking_msg = await async_call(say, "Thinking...", thread_ts=thread_ts)

    # Get conversation history for this thread
    conversation_history = _get_conversation_history(thread_ts)

    # Search for relevant chunks
    chunks = await _search_chunks(text)

    # Record access for each chunk
    for chunk in chunks:
        await record_chunk_access(
            chunk_id=chunk.chunk_id,
            slack_user_id=user_id,
            query_context=text[:500],
        )

    # Generate answer with conversation context
    answer = await _generate_answer(text, chunks, conversation_history)

    # Store this exchange in conversation history
    _add_to_conversation(thread_ts, "user", text)
    _add_to_conversation(thread_ts, "assistant", answer)

    # Build response blocks
    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": answer},
        }
    ]

    # Add source references
    if chunks:
        source_text = "*Sources:*\n" + "\n".join(
            f"• {chunk.page_title}" for chunk in chunks[:3]
        )
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": source_text}]
        })

    # Update thinking message with answer
    try:
        response = await async_call(
            client.chat_update,
            channel=channel,
            ts=thinking_msg["ts"],
            text=answer,
            blocks=blocks,
        )

        # Always add feedback buttons (even for "no results" responses)
        feedback_msg = await async_call(
            client.chat_postMessage,
            channel=channel,
            thread_ts=thread_ts,
            blocks=_create_feedback_buttons(thinking_msg["ts"]),
            text="Was this helpful?",
        )

        # Store chunk IDs for feedback (empty list if no results)
        chunk_ids = [c.chunk_id for c in chunks] if chunks else []
        pending_feedback[thinking_msg["ts"]] = chunk_ids

        # Record bot response for behavioral tracking (Phase 10.5)
        try:
            await record_bot_response(
                response_ts=thinking_msg["ts"],
                thread_ts=thread_ts,
                channel_id=channel,
                user_id=user_id,
                query=text,
                response_text=answer,
                chunk_ids=chunk_ids,
            )
        except Exception as be:
            logger.warning(f"Failed to record bot response: {be}")

    except Exception as e:
        logger.error(f"Failed to update message: {e}")


async def _handle_feedback_action(body: dict, client: WebClient) -> None:
    """Handle feedback button click.

    For 'helpful' feedback: submits directly.
    For negative feedback (incorrect, outdated, confusing): opens a modal
    to capture details before submission (Phase 10.6).
    """
    await init_db()

    action = body["actions"][0]
    action_id = action["action_id"]
    user_id = body["user"]["id"]
    channel = body["channel"]["id"]
    trigger_id = body.get("trigger_id")

    # Parse action_id: feedback_{type}_{message_ts}
    parts = action_id.split("_")
    if len(parts) < 3:
        return

    feedback_type = parts[1]
    message_ts = "_".join(parts[2:])

    # Get chunks associated with this answer
    chunk_ids = pending_feedback.get(message_ts, [])

    if not chunk_ids:
        await client.chat_postEphemeral(
            channel=channel,
            user=user_id,
            text="Thanks for your feedback! (Note: Could not find associated chunks)",
        )
        return

    # For negative feedback, open a modal to capture details (Phase 10.6)
    if feedback_type in ("incorrect", "outdated", "confusing") and trigger_id:
        try:
            # Select the appropriate modal builder
            modal_builders = {
                "incorrect": build_incorrect_feedback_modal,
                "outdated": build_outdated_feedback_modal,
                "confusing": build_confusing_feedback_modal,
            }
            build_modal = modal_builders[feedback_type]

            # Build and open the modal
            modal_view = build_modal(
                message_ts=message_ts,
                chunk_ids=chunk_ids,
                channel_id=channel,
                reporter_id=user_id,
            )

            await client.views_open(
                trigger_id=trigger_id,
                view=modal_view,
            )

            logger.info(f"Opened {feedback_type} feedback modal for user {user_id}")
            return  # Modal submission handler will handle the rest

        except Exception as e:
            logger.error(f"Failed to open feedback modal: {e}")
            # Fall through to direct submission as fallback

    # Direct submission for 'helpful' feedback (or modal fallback)
    try:
        user_info = await client.users_info(user=user_id)
        username = user_info["user"]["name"]
    except Exception:
        username = user_id

    # Submit feedback for each chunk
    for chunk_id in chunk_ids:
        await submit_feedback(
            chunk_id=chunk_id,
            slack_user_id=user_id,
            slack_username=username,
            feedback_type=feedback_type,
            slack_channel_id=channel,
            query_context=None,
            conversation_thread_ts=message_ts,
        )

    # Check for auto-escalation on negative feedback (fallback path only)
    if feedback_type in ("outdated", "incorrect", "confusing"):
        try:
            from knowledge_base.slack.admin_escalation import check_auto_escalation
            for chunk_id in chunk_ids:
                await check_auto_escalation(chunk_id, feedback_type, client, channel)
        except Exception as ae:
            logger.warning(f"Failed to check auto-escalation: {ae}")

    # Clean up pending feedback (but keep copy for escalation)
    chunk_ids_copy = chunk_ids.copy()
    pending_feedback.pop(message_ts, None)

    # Update the feedback buttons to show submitted
    feedback_text = {
        "helpful": "Thanks! Glad it helped!",
        "outdated": "Thanks! We'll review this content.",
        "incorrect": "Thanks! We'll investigate this.",
        "confusing": "Thanks! We'll try to clarify.",
    }

    # Remove buttons and show thank you
    try:
        await client.chat_update(
            channel=channel,
            ts=body["message"]["ts"],
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"_{feedback_text.get(feedback_type, 'Thanks for your feedback!')}_"
                    }
                }
            ],
            text=feedback_text.get(feedback_type, "Thanks!"),
        )
    except Exception as e:
        logger.error(f"Failed to update feedback message: {e}")

    # Offer admin help for negative feedback (fallback path only)
    if feedback_type in ("outdated", "incorrect", "confusing"):
        try:
            from knowledge_base.slack.admin_escalation import offer_admin_help
            await offer_admin_help(
                client=client,
                channel_id=channel,
                user_id=user_id,
                message_ts=message_ts,
                feedback_type=feedback_type,
                chunk_ids=chunk_ids_copy,
            )
        except Exception as ae:
            logger.warning(f"Failed to offer admin help: {ae}")


async def _handle_reaction_event(event: dict, client: WebClient) -> None:
    """Handle emoji reaction for behavioral signals (Phase 10.5)."""
    await init_db()

    try:
        item_ts = event.get("item", {}).get("ts")
        user_id = event.get("user")
        reaction = event.get("reaction")

        if not item_ts or not user_id or not reaction:
            return

        # Get bot's user ID to ignore self-reactions
        try:
            auth_response = await client.auth_test()
            bot_user_id = auth_response.get("user_id", "")
        except Exception:
            bot_user_id = ""

        signal = await process_reaction(
            item_ts=item_ts,
            user_id=user_id,
            reaction=reaction,
            bot_user_id=bot_user_id,
        )

        if signal:
            logger.info(
                f"Recorded reaction signal: {reaction} -> {signal.signal_type} "
                f"(value={signal.signal_value})"
            )

    except Exception as e:
        logger.warning(f"Failed to process reaction: {e}")


async def _handle_thread_message_event(event: dict) -> None:
    """Handle thread message for behavioral signals (Phase 10.5)."""
    await init_db()

    try:
        thread_ts = event.get("thread_ts")
        user_id = event.get("user")
        text = event.get("text", "")

        if not thread_ts or not user_id or not text:
            return

        # We don't have easy access to bot_user_id here, but we can skip bot messages
        # via the bot_id check in create_app

        signal = await process_thread_message(
            thread_ts=thread_ts,
            user_id=user_id,
            text=text,
            bot_user_id="",  # Already filtered in create_app
        )

        if signal:
            logger.info(
                f"Recorded thread signal: {signal.signal_type} "
                f"(value={signal.signal_value})"
            )

    except Exception as e:
        logger.warning(f"Failed to process thread message: {e}")


def run_http_mode(port: int = 8080) -> None:
    """Run Slack bot in HTTP mode for Cloud Run using Starlette.

    This mode is suitable for serverless deployments where the bot
    receives events via HTTP webhooks from Slack.

    Args:
        port: Port to listen on (default 8080 for Cloud Run)
    """
    try:
        from slack_bolt.adapter.starlette.async_handler import AsyncSlackRequestHandler
        from starlette.applications import Starlette
        from starlette.routing import Route
        from starlette.responses import JSONResponse
        import uvicorn
    except ImportError as e:
        raise ImportError(
            "Starlette and uvicorn are required for HTTP mode. "
            "Install with: pip install starlette uvicorn"
        ) from e

    bolt_app = create_async_app()
    handler = AsyncSlackRequestHandler(bolt_app)

    async def health(request):
        """Health check endpoint."""
        return JSONResponse({"status": "healthy", "service": "slack-bot"})

    async def slack_events(request):
        """Handle Slack events via HTTP."""
        return await handler.handle(request)

    starlette_app = Starlette(
        routes=[
            Route("/health", endpoint=health, methods=["GET"]),
            Route("/slack/events", endpoint=slack_events, methods=["POST"]),
        ]
    )

    logger.info(f"Starting Slack bot in HTTP mode on port {port}...")
    uvicorn.run(starlette_app, host="0.0.0.0", port=port)


def run_bot(port: int = 3000, use_socket_mode: bool = False) -> None:
    """Run the Slack bot.

    Args:
        port: Port for HTTP mode
        use_socket_mode: Use Socket Mode instead of HTTP (requires SLACK_APP_TOKEN)
    """
    app = create_app()

    if use_socket_mode:
        if not settings.SLACK_APP_TOKEN:
            raise ValueError("SLACK_APP_TOKEN required for socket mode")
        handler = SocketModeHandler(app, settings.SLACK_APP_TOKEN)
        logger.info("Starting bot in Socket Mode...")
        handler.start()
    else:
        logger.info(f"Starting bot on port {port}...")
        app.start(port=port)


class SecretRedactingFilter(logging.Filter):
    """Filter to redact sensitive information from logs."""

    # Patterns for common secrets
    SECRET_PATTERNS = [
        (re.compile(r"(api[_-]?key[\s:=]+)[\w-]{20,}", re.IGNORECASE), r"\1[REDACTED]"),
        (re.compile(r"(token[\s:=]+)[\w-]{20,}", re.IGNORECASE), r"\1[REDACTED]"),
        (re.compile(r"(password[\s:=]+)\S+", re.IGNORECASE), r"\1[REDACTED]"),
        (re.compile(r"(secret[\s:=]+)\S+", re.IGNORECASE), r"\1[REDACTED]"),
        (re.compile(r"(bearer\s+)[\w-]+", re.IGNORECASE), r"\1[REDACTED]"),
        (re.compile(r"(authorization[\s:]+bearer\s+)[\w-]+", re.IGNORECASE), r"\1[REDACTED]"),
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact secrets from log messages."""
        if isinstance(record.msg, str):
            for pattern, replacement in self.SECRET_PATTERNS:
                record.msg = pattern.sub(replacement, record.msg)
        return True


def main() -> None:
    """Main entry point with CLI argument parsing."""
    parser = argparse.ArgumentParser(description="Run the Slack bot")
    parser.add_argument(
        "--http",
        action="store_true",
        help="Run in HTTP mode (for Cloud Run)",
    )
    parser.add_argument(
        "--socket",
        action="store_true",
        help="Run in Socket Mode",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", 8080)),
        help="Port to listen on (default: 8080 or PORT env var)",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logging.getLogger().addFilter(SecretRedactingFilter())

    if args.http:
        run_http_mode(port=args.port)
    elif args.socket:
        run_bot(use_socket_mode=True)
    else:
        run_bot(port=args.port)


if __name__ == "__main__":
    main()
