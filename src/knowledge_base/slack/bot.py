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
from knowledge_base.core.qa import (
    generate_answer,
    generate_answer_stream,
    generate_quick_answer,
    search_with_expansion,
)
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

    # Register governance admin handlers (approve/reject/revert buttons + queue command)
    try:
        from knowledge_base.slack.governance_admin import register_governance_handlers
        register_governance_handlers(app)
        logger.info("Governance admin handlers registered")
    except Exception as e:
        logger.warning(f"Failed to register governance admin handlers: {e}")

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

    # Register governance admin handlers (approve/reject/revert buttons + queue command)
    try:
        from knowledge_base.slack.governance_admin import register_governance_handlers
        register_governance_handlers(app)
        logger.info("Governance admin handlers registered")
    except Exception as e:
        logger.warning(f"Failed to register governance admin handlers: {e}")

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


async def _search_chunks(query: str, limit: int | None = None) -> list[SearchResult]:
    """Search for relevant chunks using Graphiti hybrid search with query expansion.

    Delegates to core.qa.search_with_expansion for reusability across interfaces.
    Uses LLM-based query expansion to generate multiple search variants for
    better recall on broad questions.
    """
    return await search_with_expansion(query, limit)


async def _generate_answer(
    question: str,
    chunks: list[SearchResult],
    conversation_history: list[dict[str, str]] | None = None,
) -> str:
    """Generate an answer using LLM with retrieved chunks.

    Delegates to core.qa.generate_answer for reusability across interfaces.
    """
    return await generate_answer(question, chunks, conversation_history)


def _split_text_into_blocks(text: str, max_chars: int = 3000) -> list[dict]:
    """Split long text into multiple Slack section blocks.

    Slack section blocks have a 3000 character text limit.
    This splits at paragraph boundaries to stay within limits.
    """
    if len(text) <= max_chars:
        return [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]

    blocks = []
    remaining = text
    while remaining:
        if len(remaining) <= max_chars:
            blocks.append(
                {"type": "section", "text": {"type": "mrkdwn", "text": remaining}}
            )
            break

        # Try to split at a paragraph boundary
        split_pos = remaining.rfind("\n\n", 0, max_chars)
        if split_pos < max_chars // 2:
            # No good paragraph break, try single newline
            split_pos = remaining.rfind("\n", 0, max_chars)
        if split_pos < max_chars // 2:
            # No good newline break, split at space
            split_pos = remaining.rfind(" ", 0, max_chars)
        if split_pos < 1:
            # Hard cut as last resort
            split_pos = max_chars

        chunk = remaining[:split_pos].rstrip()
        remaining = remaining[split_pos:].lstrip()
        if chunk:
            blocks.append(
                {"type": "section", "text": {"type": "mrkdwn", "text": chunk}}
            )

    return blocks


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


def _build_sources_block(chunks: list) -> dict | None:
    """Build the sources context block from search chunks.

    Returns None if no usable sources.  De-duplicates by title and caps at 3.
    """
    if not chunks:
        return None
    source_lines: list[str] = []
    seen_titles: set[str] = set()
    for chunk in chunks:
        title = chunk.page_title
        if not title or not title.strip() or title in seen_titles:
            continue
        seen_titles.add(title)
        if chunk.doc_type == "quick_fact":
            reviewer = chunk.metadata.get("reviewed_by", "")
            if reviewer:
                source_lines.append(f"• {title} _(approved by {reviewer})_")
            else:
                source_lines.append(f"• {title}")
        else:
            source_lines.append(f"• {title}")
        if len(source_lines) >= 3:
            break
    if not source_lines:
        return None
    return {
        "type": "context",
        "elements": [
            {"type": "mrkdwn", "text": "*Sources:*\n" + "\n".join(source_lines)}
        ],
    }


def _render_streaming_answer(
    quick: str,
    detailed: str,
    chunks: list | None,
    streaming: bool,
) -> tuple[str, list[dict]]:
    """Build (fallback_text, blocks) for a streaming answer message.

    Args:
        quick: One-sentence preliminary answer (may be empty).
        detailed: Accumulated detailed answer text so far.
        chunks: Source chunks to render in a context block.  Pass None to skip.
        streaming: If True, append a streaming indicator so users know the
            answer is still growing.

    Returns:
        (fallback_text, blocks) suitable for chat.update.
    """
    parts: list[str] = []
    if quick:
        parts.append(f"*Quick answer:* {quick}")
    body = detailed
    if streaming:
        body = (body or "") + " _(streaming...)_"
    if body:
        parts.append(body)

    full_text = "\n\n".join(parts) if parts else "Working on it..."
    blocks = _split_text_into_blocks(full_text)

    if chunks:
        sources_block = _build_sources_block(chunks)
        if sources_block:
            blocks.append(sources_block)

    fallback_text = full_text[:4000]
    return fallback_text, blocks


async def _stream_answer_to_slack(
    *,
    client: Any,
    channel: str,
    thinking_ts: str,
    text: str,
    chunks: list,
    conversation_history: list[dict[str, str]] | None,
    async_call: Any,
) -> str:
    """Run the staged streaming response: status -> quick answer -> stream -> final.

    Returns the final detailed answer text so the caller can store it in
    conversation history and feedback tracking.

    Falls back to ``generate_answer`` (non-streaming) if the streaming LLM
    call raises before producing any text.
    """
    update_interval = settings.SLACK_STREAMING_UPDATE_INTERVAL
    quick_enabled = settings.SLACK_QUICK_ANSWER_ENABLED

    # Stage 2: search-complete status
    try:
        await async_call(
            client.chat_update,
            channel=channel,
            ts=thinking_ts,
            text=f"Found {len(chunks)} sources. Generating quick answer...",
        )
    except Exception:  # noqa: BLE001
        pass

    # Stage 3: quick answer (best-effort, may be empty)
    quick = ""
    if quick_enabled:
        quick = await generate_quick_answer(text, chunks)
        # Guard against truncated/junk responses (e.g. Gemini 2.5 thinking
        # tokens consumed the whole budget, leaving 3 chars).  If the answer
        # is too short to be meaningful, skip showing it.
        min_len = settings.SLACK_QUICK_ANSWER_MIN_LENGTH
        if quick and len(quick) < min_len:
            logger.info(
                "Quick answer too short (%d chars < %d min), skipping: %r",
                len(quick), min_len, quick,
            )
            quick = ""
        if quick:
            try:
                fallback, blocks = _render_streaming_answer(
                    quick=quick,
                    detailed="_Generating detailed answer..._",
                    chunks=None,
                    streaming=False,
                )
                await async_call(
                    client.chat_update,
                    channel=channel,
                    ts=thinking_ts,
                    text=fallback,
                    blocks=blocks,
                )
            except Exception:  # noqa: BLE001
                pass

    # Stage 4: stream the detailed answer
    buffer = ""
    last_update = 0.0
    received_any = False

    try:
        async for fragment in generate_answer_stream(text, chunks, conversation_history):
            if not fragment:
                continue
            buffer += fragment
            received_any = True
            now = asyncio.get_event_loop().time()
            if now - last_update >= update_interval:
                fallback, blocks = _render_streaming_answer(
                    quick=quick, detailed=buffer, chunks=None, streaming=True
                )
                try:
                    await async_call(
                        client.chat_update,
                        channel=channel,
                        ts=thinking_ts,
                        text=fallback,
                        blocks=blocks,
                    )
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"Streaming chat.update failed: {e}")
                last_update = now
    except Exception as e:  # noqa: BLE001
        logger.error(f"Streaming generation failed: {e}", exc_info=True)
        if not received_any:
            # Fall back to non-streaming generate so the user still gets an answer
            buffer = await generate_answer(text, chunks, conversation_history)

    # Stage 5: final update with sources, no streaming indicator
    if not buffer.strip():
        buffer = "I couldn't generate an answer at this time. Please try again later."

    fallback, blocks = _render_streaming_answer(
        quick=quick, detailed=buffer, chunks=chunks, streaming=False
    )
    try:
        await async_call(
            client.chat_update,
            channel=channel,
            ts=thinking_ts,
            text=fallback,
            blocks=blocks,
        )
    except Exception as e:  # noqa: BLE001
        logger.error(f"Final chat.update failed: {e}", exc_info=True)
        # Last resort: post answer as new message
        try:
            await async_call(
                client.chat_postMessage,
                channel=channel,
                thread_ts=thinking_ts,
                text=fallback,
                blocks=blocks,
            )
        except Exception as e2:  # noqa: BLE001
            logger.error(f"Fallback post also failed: {e2}", exc_info=True)

    return buffer.strip()


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

    logger.info(f"Processing question: '{text[:80]}'")

    # Get user info
    try:
        user_info = await async_call(client.users_info, user=user_id)
        username = user_info["user"]["name"]
    except Exception:
        username = user_id

    # Send "thinking" message
    initial_thinking_text = (
        "Got it, checking knowledge base..."
        if settings.SLACK_STREAMING_ENABLED
        else "Thinking..."
    )
    try:
        thinking_msg = await async_call(say, initial_thinking_text, thread_ts=thread_ts)
        logger.info(f"Posted 'Thinking...' message ts={thinking_msg.get('ts', 'unknown')}")
    except Exception as e:
        logger.error(f"Failed to post 'Thinking...' message: {e}", exc_info=True)
        # Try direct chat.postMessage as fallback
        try:
            thinking_msg = await async_call(
                client.chat_postMessage,
                channel=channel,
                thread_ts=thread_ts,
                text=initial_thinking_text,
            )
            logger.info(f"Posted 'Thinking...' via fallback, ts={thinking_msg.get('ts', 'unknown')}")
        except Exception as e2:
            logger.error(f"Fallback 'Thinking...' also failed: {e2}", exc_info=True)
            return

    thinking_ts = thinking_msg.get("ts")

    # Get conversation history for this thread (used by both code paths)
    conversation_history = _get_conversation_history(thread_ts)

    streaming_mode = settings.SLACK_STREAMING_ENABLED and bool(thinking_ts)

    # In streaming mode, run a lightweight ticker DURING search so users see
    # progress (search can take 2+ minutes on the knowledge graph).
    search_stop = asyncio.Event()
    search_ticker_task: Any = None
    if streaming_mode:
        search_messages = [
            "Got it, checking knowledge base...",
            "Searching documents and graph relationships...",
            "Reading through the knowledge graph...",
            "Cross-referencing related topics...",
            "Still searching, knowledge graph is large...",
            "Almost done with the search, hang tight...",
        ]

        async def _search_ticker() -> None:
            interval = settings.SLACK_SEARCH_TICKER_INTERVAL
            for msg in search_messages:
                if search_stop.is_set():
                    return
                try:
                    await async_call(
                        client.chat_update,
                        channel=channel,
                        ts=thinking_ts,
                        text=msg,
                    )
                except Exception:  # noqa: BLE001
                    pass
                try:
                    await asyncio.wait_for(search_stop.wait(), timeout=interval)
                    return
                except asyncio.TimeoutError:
                    pass

        search_ticker_task = asyncio.ensure_future(_search_ticker())

    # Search for relevant chunks (always needed, regardless of streaming mode)
    try:
        chunks = await _search_chunks(text)
        logger.info(f"Search returned {len(chunks)} chunks")
    finally:
        if search_ticker_task is not None:
            search_stop.set()
            try:
                await search_ticker_task
            except Exception:  # noqa: BLE001
                pass

    if streaming_mode:
        # Streaming flow: status -> quick answer -> stream tokens -> final
        answer = await _stream_answer_to_slack(
            client=client,
            channel=channel,
            thinking_ts=thinking_ts,
            text=text,
            chunks=chunks,
            conversation_history=conversation_history,
            async_call=async_call,
        )
        logger.info(f"Streaming flow finished: {len(answer)} chars")
    else:
        # Legacy non-streaming flow: rotating status + single chat.update at end
        progress_messages = [
            "Searching the knowledge base...",
            "Waking up the agents...",
            "Scanning the knowledge graph...",
            "Exploring related topics...",
            "Gathering relevant documents...",
            "Cross-referencing sources...",
            "Reading through the results...",
            "Connecting the dots...",
            "Composing a comprehensive answer...",
            "Almost there, polishing the response...",
            "Putting the finishing touches...",
        ]
        progress_stop = asyncio.Event()

        async def _progress_ticker() -> None:
            """Update the thinking message with rotating status every 7 seconds."""
            if not thinking_ts:
                return
            for msg in progress_messages:
                if progress_stop.is_set():
                    return
                try:
                    await async_call(
                        client.chat_update,
                        channel=channel,
                        ts=thinking_ts,
                        text=msg,
                    )
                except Exception:
                    pass
                try:
                    await asyncio.wait_for(progress_stop.wait(), timeout=7.0)
                    return
                except asyncio.TimeoutError:
                    pass

        ticker_task = asyncio.ensure_future(_progress_ticker())
        try:
            answer = await _generate_answer(text, chunks, conversation_history)
            logger.info(f"Generated answer: {len(answer)} chars")
        finally:
            progress_stop.set()
            await ticker_task

    # Store this exchange in conversation history
    _add_to_conversation(thread_ts, "user", text)
    _add_to_conversation(thread_ts, "assistant", answer)

    if not streaming_mode:
        # Legacy non-streaming flow needs to render blocks and call chat.update.
        # In streaming mode this was already done by _stream_answer_to_slack.
        blocks = _split_text_into_blocks(answer)
        sources_block = _build_sources_block(chunks)
        if sources_block:
            blocks.append(sources_block)

        fallback_text = answer[:4000] if len(answer) > 4000 else answer

        if not thinking_ts:
            logger.error("No timestamp in thinking message response, cannot update")
            return

        try:
            response = await async_call(
                client.chat_update,
                channel=channel,
                ts=thinking_ts,
                text=fallback_text,
                blocks=blocks,
            )
            logger.info("Updated message with answer")
        except Exception as e:
            logger.error("Failed to update message", exc_info=True)
            try:
                await async_call(
                    client.chat_postMessage,
                    channel=channel,
                    thread_ts=thread_ts,
                    text=fallback_text,
                    blocks=blocks,
                )
                logger.info("Posted answer as new message (fallback)")
            except Exception as e2:
                logger.error("Failed to post fallback message", exc_info=True)

    # Always add feedback buttons (even for "no results" responses)
    try:
        feedback_msg = await async_call(
            client.chat_postMessage,
            channel=channel,
            thread_ts=thread_ts,
            blocks=_create_feedback_buttons(thinking_ts),
            text="Was this helpful?",
        )
        logger.info("Posted feedback buttons")

        # Store chunk IDs for feedback (empty list if no results)
        chunk_ids = [c.chunk_id for c in chunks] if chunks else []
        pending_feedback[thinking_ts] = chunk_ids

        # Record bot response for behavioral tracking
        try:
            await record_bot_response(
                response_ts=thinking_ts,
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
        logger.error(f"Failed to post feedback buttons: {e}")

    # Record access for each chunk (fire-and-forget, don't block the response)
    asyncio.ensure_future(_record_chunk_accesses(chunks, user_id, text))


async def _record_chunk_accesses(
    chunks: list,
    user_id: str,
    query_text: str,
) -> None:
    """Record access for all chunks in the background (parallel)."""
    tasks = [
        record_chunk_access(
            chunk_id=chunk.chunk_id,
            slack_user_id=user_id,
            query_context=query_text[:500],
        )
        for chunk in chunks
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.warning("Failed to record chunk access for %s: %s", chunks[i].chunk_id, result)


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
            feedback_buttons_ts = body["message"]["ts"]
            modal_view = build_modal(
                message_ts=message_ts,
                chunk_ids=chunk_ids,
                channel_id=channel,
                reporter_id=user_id,
                feedback_buttons_ts=feedback_buttons_ts,
            )

            await client.views_open(
                trigger_id=trigger_id,
                view=modal_view,
            )

            logger.info(f"Opened {feedback_type} feedback modal")
            return  # Modal submission handler will handle the rest

        except Exception as e:
            logger.error(f"Failed to open feedback modal: {e}")
            # Fall through to direct submission as fallback

    # Update the feedback buttons to show submitted IMMEDIATELY (before slow DB writes)
    feedback_text = {
        "helpful": "Thanks! Glad it helped!",
        "outdated": "Thanks! We'll review this content.",
        "incorrect": "Thanks! We'll investigate this.",
        "confusing": "Thanks! We'll try to clarify.",
    }

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

    # Clean up pending feedback
    pending_feedback.pop(message_ts, None)

    # Submit feedback for each chunk in background (fire-and-forget)
    asyncio.ensure_future(_submit_feedback_background(
        chunk_ids=chunk_ids,
        user_id=user_id,
        feedback_type=feedback_type,
        channel=channel,
        message_ts=message_ts,
        client=client,
    ))


async def _submit_feedback_background(
    chunk_ids: list[str],
    user_id: str,
    feedback_type: str,
    channel: str,
    message_ts: str,
    client: Any,
) -> None:
    """Submit feedback for all chunks in the background (parallel)."""
    try:
        user_info = await client.users_info(user=user_id)
        username = user_info["user"]["name"]
    except Exception:
        username = user_id

    tasks = [
        submit_feedback(
            chunk_id=chunk_id,
            slack_user_id=user_id,
            slack_username=username,
            feedback_type=feedback_type,
            slack_channel_id=channel,
            query_context=None,
            conversation_thread_ts=message_ts,
        )
        for chunk_id in chunk_ids
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.warning("Failed to submit feedback for %s: %s", chunk_ids[i], result)

    logger.info("Submitted %s feedback for %d chunks", feedback_type, len(chunk_ids))

    # Check for auto-escalation on negative feedback
    if feedback_type in ("outdated", "incorrect", "confusing"):
        try:
            from knowledge_base.slack.admin_escalation import check_auto_escalation
            for chunk_id in chunk_ids:
                await check_auto_escalation(chunk_id, feedback_type, client, channel)
        except Exception as ae:
            logger.warning(f"Failed to check auto-escalation: {ae}")

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
                chunk_ids=chunk_ids,
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

    from contextlib import asynccontextmanager
    from sqlalchemy import text

    bolt_app = create_async_app()
    handler = AsyncSlackRequestHandler(bolt_app)

    @asynccontextmanager
    async def lifespan(app):
        """Initialize database before accepting requests."""
        await init_db()
        logger.info("Database initialized at startup")
        yield

    async def health(request):
        """Health check endpoint with database verification."""
        try:
            async with async_session_maker() as session:
                await session.execute(text("SELECT 1"))
            return JSONResponse({"status": "healthy", "service": "slack-bot", "db": "ok"})
        except Exception as e:
            logger.error("Health check DB failure: %s", e)
            return JSONResponse(
                {"status": "degraded", "service": "slack-bot", "db": "unavailable"},
                status_code=503,
            )

    async def slack_events(request):
        """Handle Slack events via HTTP."""
        return await handler.handle(request)

    starlette_app = Starlette(
        routes=[
            Route("/health", endpoint=health, methods=["GET"]),
            Route("/slack/events", endpoint=slack_events, methods=["POST"]),
        ],
        lifespan=lifespan,
    )

    logger.info(f"Starting Slack bot in HTTP mode on port {port}...")
    uvicorn.run(starlette_app, host="0.0.0.0", port=port)


def run_bot(port: int = 3000, use_socket_mode: bool = False) -> None:
    """Run the Slack bot.

    Args:
        port: Port for HTTP mode
        use_socket_mode: Use Socket Mode instead of HTTP (requires SLACK_APP_TOKEN)
    """
    import asyncio
    asyncio.run(init_db())
    logger.info("Database initialized at startup")

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

    # force=True is required because Settings() triggers logging.warning()
    # during import, which implicitly calls basicConfig() with default
    # level=WARNING. Without force=True, our explicit call is a no-op
    # and all INFO-level logs are silently dropped.
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s:%(name)s:%(message)s",
        force=True,
    )
    logging.getLogger().addFilter(SecretRedactingFilter())

    logger.info("Slack bot starting (logging configured at INFO level)")

    if args.http:
        run_http_mode(port=args.port)
    elif args.socket:
        run_bot(use_socket_mode=True)
    else:
        run_bot(port=args.port)


if __name__ == "__main__":
    main()
