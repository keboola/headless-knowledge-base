"""Handler for /create-knowledge slash command.

Creates quick knowledge directly in ChromaDB (source of truth).
No SQLite intermediate storage - per docs/ARCHITECTURE.md.
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any

from slack_sdk import WebClient

from knowledge_base.vectorstore.indexer import ChunkData, VectorIndexer

logger = logging.getLogger(__name__)


async def handle_create_knowledge(ack: Any, command: dict, client: WebClient) -> None:
    """Handle the /create-knowledge slash command.

    Creates a new knowledge chunk directly in ChromaDB (source of truth).
    No intermediate SQLite storage needed.

    NOTE: This uses background task processing to avoid Slack's 3-second timeout
    in Cloud Run deployments. The indexing operation (embedding generation + ChromaDB upload)
    can take 2-4 seconds, which would cause "operation_timeout" errors.
    """
    # CRITICAL: Acknowledge immediately to avoid timeout
    await ack()

    text = command.get("text", "").strip()
    user_id = command.get("user_id")
    user_name = command.get("user_name", "unknown")
    channel_id = command.get("channel_id")

    if not text:
        await client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="Please provide the information you want to save. Usage: `/create-knowledge <fact>`",
        )
        return

    # Send immediate response to user - don't wait for indexing
    await client.chat_postEphemeral(
        channel=channel_id,
        user=user_id,
        text="⏳ Saving knowledge... (this may take a few seconds)",
    )

    # Process the indexing in a background task to avoid blocking
    async def process_indexing():
        """Background task to handle the actual indexing work."""
        try:
            # Create unique IDs
            page_id = f"quick_{uuid.uuid4().hex[:16]}"
            chunk_id = f"{page_id}_0"
            now = datetime.utcnow()

            # Create ChunkData for direct ChromaDB indexing (no SQLite)
            chunk_data = ChunkData(
                chunk_id=chunk_id,
                content=text,
                page_id=page_id,
                page_title=f"Quick Fact by {user_name}",
                chunk_index=0,
                space_key="QUICK",
                url=f"slack://user/{user_id}",
                author=user_name,
                created_at=now.isoformat(),
                updated_at=now.isoformat(),
                chunk_type="text",
                parent_headers="[]",
                quality_score=100.0,  # Start high for manually created knowledge
                access_count=0,
                feedback_count=0,
                owner=user_name,  # Creator is the owner
                reviewed_by="",
                reviewed_at="",
                classification="internal",
                doc_type="quick_fact",
                topics="[]",
                audience="[]",
                complexity="",
                summary=text[:200] if len(text) > 200 else text,
            )

            # Index directly to ChromaDB (source of truth)
            # This involves: 1) embedding generation (Vertex AI call ~1-2s)
            #                2) ChromaDB upload (~1-2s)
            indexer = VectorIndexer()
            await indexer.index_single_chunk(chunk_data)

            logger.info(f"Created and indexed quick knowledge: {chunk_id}")

            # Send success message
            await client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=f"✅ Knowledge saved! I'll remember that.\n> {text}",
            )

        except Exception as e:
            logger.error(f"Failed to create knowledge: {e}", exc_info=True)
            await client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=f"❌ Error saving knowledge: {str(e)}",
            )

    # Start the background task and return immediately
    asyncio.create_task(process_indexing())

def register_quick_knowledge_handler(app):
    """Register the command handler with the Slack app."""
    app.command("/create-knowledge")(handle_create_knowledge)
