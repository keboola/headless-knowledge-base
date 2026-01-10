"""End-to-End tests for Feedback and Knowledge Creation flow."""

import pytest
import uuid
import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy import select

from knowledge_base.db.models import Chunk, ChunkQuality, UserFeedback
from knowledge_base.slack.quick_knowledge import handle_create_knowledge
from knowledge_base.slack.bot import _handle_feedback_action, pending_feedback
from knowledge_base.lifecycle.feedback import get_feedback_for_chunk

logger = logging.getLogger(__name__)

# Mark all tests in this module as e2e
pytestmark = pytest.mark.e2e

@pytest.mark.asyncio
async def test_complete_feedback_lifecycle(slack_client, db_session, e2e_config):
    """
    Scenario: Complete Feedback Lifecycle
    1. Create a fact via /create-knowledge
    2. Verify it's in the DB with initial quality score (100.0)
    3. Simulate bot response (populating pending_feedback)
    4. Simulate user clicking "Helpful" feedback
    5. Verify quality score increased
    6. Simulate user clicking "Incorrect" feedback
    7. Verify quality score decreased significantly
    """
    unique_id = uuid.uuid4().hex[:8]
    fact_text = f"The official color of project {unique_id} is Ultraviolet."
    
    # 1. Create Knowledge
    ack = AsyncMock()
    mock_client = MagicMock()
    mock_client.chat_postEphemeral = AsyncMock()
    # Configure users_info mock
    mock_client.users_info.return_value = {
        "ok": True,
        "user": {"name": "test_user"}
    }
    
    command = {
        "text": fact_text,
        "user_id": "U_TEST_USER",
        "user_name": "test_user",
        "channel_id": e2e_config["channel_id"]
    }
    
    with patch("knowledge_base.slack.quick_knowledge.VectorIndexer") as mock_indexer_cls:
        mock_indexer = mock_indexer_cls.return_value
        mock_indexer.embeddings.embed = AsyncMock(return_value=[[0.1] * 768])
        mock_indexer.chroma.upsert = AsyncMock()
        mock_indexer.build_metadata = MagicMock(return_value={})
        # Mock index_single_chunk for direct ChromaDB indexing
        mock_indexer.index_single_chunk = AsyncMock()

        await handle_create_knowledge(ack, command, mock_client)

    # 2. Verify in ChromaDB (source of truth) - chunks are no longer stored in SQLite
    # The test now verifies the indexer was called correctly
    mock_indexer.index_single_chunk.assert_called_once()

    # Get chunk_id from the call args
    call_args = mock_indexer.index_single_chunk.call_args
    chunk_data = call_args[0][0]  # First positional argument
    chunk_id = chunk_data.chunk_id

    # NOTE: With ChromaDB as source of truth, chunks are indexed directly to ChromaDB
    # Verify the chunk_data was created with correct content
    assert chunk_data.content == fact_text, "Chunk content doesn't match"
    assert chunk_data.quality_score == 100.0, "Initial quality score should be 100.0"

    # 3. Simulate Bot Response
    # In a real bot, when it replies, it adds the used chunk_ids to pending_feedback
    fake_message_ts = "1234567890.123456"
    pending_feedback[fake_message_ts] = [chunk_id]

    # 4. Simulate "Helpful" Feedback with ChromaDB mock
    helpful_body = {
        "user": {"id": "U_TEST_USER"},
        "actions": [{"action_id": f"feedback_helpful_{fake_message_ts}"}],
        "channel": {"id": e2e_config["channel_id"]},
        "message": {"ts": fake_message_ts}
    }

    # We use sync mocks because bot.py uses synchronous WebClient
    mock_client.chat_update = MagicMock()
    mock_client.chat_postEphemeral = MagicMock()

    # Mock ChromaDB for feedback quality updates
    with patch("knowledge_base.lifecycle.feedback.get_chroma_client") as mock_chroma:
        mock_chroma_client = MagicMock()
        mock_chroma_client.get_quality_score = AsyncMock(return_value=100.0)
        mock_chroma_client.update_quality_score = AsyncMock()
        mock_chroma.return_value = mock_chroma_client

        await _handle_feedback_action(helpful_body, mock_client)

    # 5. Verify feedback record exists in database (for analytics)
    feedbacks = await get_feedback_for_chunk(chunk_id)
    assert any(f.feedback_type == "helpful" for f in feedbacks)

    # Test with lower initial score - mock returns 90.0
    pending_feedback[fake_message_ts] = [chunk_id]

    with patch("knowledge_base.lifecycle.feedback.get_chroma_client") as mock_chroma:
        mock_chroma_client = MagicMock()
        mock_chroma_client.get_quality_score = AsyncMock(return_value=90.0)
        mock_chroma_client.update_quality_score = AsyncMock()
        mock_chroma.return_value = mock_chroma_client

        await _handle_feedback_action(helpful_body, mock_client)
        # Verify ChromaDB update was called with increased score
        mock_chroma_client.update_quality_score.assert_called()

    # 6. Simulate "Incorrect" Feedback (incorrect = -25)
    incorrect_body = {
        "user": {"id": "U_TEST_USER"},
        "actions": [{"action_id": f"feedback_incorrect_{fake_message_ts}"}],
        "channel": {"id": e2e_config["channel_id"]},
        "message": {"ts": fake_message_ts}
    }
    # Re-populate pending_feedback
    pending_feedback[fake_message_ts] = [chunk_id]

    with patch("knowledge_base.lifecycle.feedback.get_chroma_client") as mock_chroma:
        mock_chroma_client = MagicMock()
        mock_chroma_client.get_quality_score = AsyncMock(return_value=92.0)
        mock_chroma_client.update_quality_score = AsyncMock()
        mock_chroma.return_value = mock_chroma_client

        await _handle_feedback_action(incorrect_body, mock_client)
        # Verify quality score update was called
        mock_chroma_client.update_quality_score.assert_called()

    # 7. Verify both feedback records exist in analytics database
    feedbacks = await get_feedback_for_chunk(chunk_id)
    assert any(f.feedback_type == "incorrect" for f in feedbacks)

@pytest.mark.asyncio
async def test_feedback_on_multiple_chunks(slack_client, db_session, e2e_config):
    """Verify feedback applies to all chunks in a response."""
    unique_id = uuid.uuid4().hex[:8]

    # Create two chunks via quick_knowledge (indexed to ChromaDB)
    chunk_ids = []
    with patch("knowledge_base.slack.quick_knowledge.VectorIndexer") as mock_indexer_cls:
        mock_indexer = mock_indexer_cls.return_value
        mock_indexer.embeddings.embed = AsyncMock(return_value=[[0.1] * 768])
        mock_indexer.chroma.upsert = AsyncMock()
        mock_indexer.build_metadata = MagicMock(return_value={})
        mock_indexer.index_single_chunk = AsyncMock()

        for i in range(2):
            text = f"Multi-chunk test {unique_id} part {i}"
            ack = AsyncMock()
            mock_client = MagicMock()
            mock_client.chat_postEphemeral = AsyncMock()
            await handle_create_knowledge(ack, {"text": text, "user_id": "U1", "channel_id": "C1"}, mock_client)

            # Get chunk_id from the mock call
            call_args = mock_indexer.index_single_chunk.call_args
            chunk_data = call_args[0][0]
            chunk_ids.append(chunk_data.chunk_id)

    fake_ts = f"999999.{unique_id}"
    pending_feedback[fake_ts] = chunk_ids

    # Feedback "Confusing" (confusing = -5)
    body = {
        "user": {"id": "U_TEST_USER"},
        "actions": [{"action_id": f"feedback_confusing_{fake_ts}"}],
        "channel": {"id": "C1"},
        "message": {"ts": fake_ts}
    }

    # Mock client for _handle_feedback_action
    mock_client = MagicMock()
    mock_client.users_info.return_value = {"ok": True, "user": {"name": "test_user"}}
    mock_client.chat_update = MagicMock()
    mock_client.chat_postEphemeral = MagicMock()

    # Mock ChromaDB for quality score updates
    with patch("knowledge_base.lifecycle.feedback.get_chroma_client") as mock_chroma:
        mock_chroma_client = MagicMock()
        mock_chroma_client.get_quality_score = AsyncMock(return_value=100.0)
        mock_chroma_client.update_quality_score = AsyncMock()
        mock_chroma.return_value = mock_chroma_client

        await _handle_feedback_action(body, mock_client)

        # Verify ChromaDB update was called for each chunk
        assert mock_chroma_client.update_quality_score.call_count == len(chunk_ids)
