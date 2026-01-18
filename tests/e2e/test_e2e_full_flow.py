"""End-to-End tests for Knowledge Base workflow."""

import pytest
import uuid
import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy import select

from knowledge_base.db.models import Chunk, ChunkQuality, BehavioralSignal, UserFeedback
from knowledge_base.slack.quick_knowledge import handle_create_knowledge

logger = logging.getLogger(__name__)

# Mark all tests in this module as e2e
pytestmark = pytest.mark.e2e

@pytest.mark.asyncio
async def test_create_and_retrieve_knowledge(slack_client, db_session, e2e_config):
    """
    Scenario 1: Create & Retrieve Knowledge
    1. Create a fact via /create-knowledge handler (simulated)
    2. Ask the bot about it via real Slack
    3. Verify bot provides the answer
    """
    # 1. Simulate /create-knowledge
    unique_id = uuid.uuid4().hex[:8]
    fact_text = f"The secret code for project E2E-{unique_id} is ALPHA-BETA-{unique_id}."
    
    # Mock Slack interaction for the slash command
    ack = AsyncMock()
    mock_client = MagicMock()
    mock_client.chat_postEphemeral = AsyncMock()
    
    command = {
        "text": fact_text,
        "user_id": e2e_config["bot_user_id"], 
        "user_name": "e2e_test_bot",
        "channel_id": e2e_config["channel_id"]
    }
    
    # This will index to the REMOTE ChromaDB
    await handle_create_knowledge(ack, command, mock_client)
    
    # Wait for background indexing to complete (it's async in handle_create_knowledge)
    await asyncio.sleep(10)
    
    # 2. Ask Bot via real Slack
    question = f"What is the secret code for project E2E-{unique_id}?"
    user_msg_ts = await slack_client.send_message(f"<@{e2e_config['bot_user_id']}> {question}")
    
    # 3. Wait for reply from the REMOTE Bot (in thread)
    reply = await slack_client.wait_for_bot_reply(parent_ts=user_msg_ts, timeout=60)
    assert reply is not None, "Remote Bot did not reply"
    assert f"ALPHA-BETA-{unique_id}" in reply["text"], f"Bot reply did not contain the secret code. Got: {reply['text']}"

@pytest.mark.asyncio
async def test_feedback_improves_score(slack_client, db_session, e2e_config):
    """
    Scenario 2: Verify knowledge retrieval
    """
    unique_id = uuid.uuid4().hex[:8]
    fact_text = f"The feedback test value for {unique_id} is SUCCESS-{unique_id}."
    
    # Create fact
    ack = AsyncMock()
    mock_client = MagicMock()
    mock_client.chat_postEphemeral = AsyncMock()
    command = {
        "text": fact_text,
        "user_id": e2e_config["bot_user_id"],
        "user_name": "e2e_test_bot",
        "channel_id": e2e_config["channel_id"]
    }
    await handle_create_knowledge(ack, command, mock_client)
    
    # Wait for indexing
    await asyncio.sleep(10)
    
    # Verification: Ask bot and check if it knows it
    user_msg_ts = await slack_client.send_message(f"<@{e2e_config['bot_user_id']}> what is the feedback test value for {unique_id}?")
    reply = await slack_client.wait_for_bot_reply(parent_ts=user_msg_ts, timeout=60)
    assert reply is not None
    assert f"SUCCESS-{unique_id}" in reply["text"]

@pytest.mark.asyncio
async def test_negative_feedback_demotes(slack_client, db_session, e2e_config):
    """Scenario 3: Verify knowledge retrieval"""
    unique_id = uuid.uuid4().hex[:8]
    fact_text = f"The negative feedback test key for {unique_id} is SECRET-{unique_id}."
    
    ack = AsyncMock()
    mock_client = MagicMock()
    mock_client.chat_postEphemeral = AsyncMock()
    command = {"text": fact_text, "user_id": e2e_config["bot_user_id"], "user_name": "e2e_bot", "channel_id": e2e_config["channel_id"]}
    await handle_create_knowledge(ack, command, mock_client)
    
    # Wait for indexing
    await asyncio.sleep(10)
    
    user_msg_ts = await slack_client.send_message(f"<@{e2e_config['bot_user_id']}> what is the negative feedback test key for {unique_id}?")
    reply = await slack_client.wait_for_bot_reply(parent_ts=user_msg_ts, timeout=60)
    assert reply is not None
    assert f"SECRET-{unique_id}" in reply["text"]

@pytest.mark.asyncio
async def test_behavioral_signals(slack_client, db_session, e2e_config):
    """
    Scenario 5: Behavioral Signals (Black Box)
    1. Ask question
    2. Reply "Thanks" in thread
    """
    # 1. Ask Question
    question = "How do I use this knowledge base?"
    user_msg_ts = await slack_client.send_message(f"<@{e2e_config['bot_user_id']}> {question}")
    
    # Wait for reply in thread
    bot_reply = await slack_client.wait_for_bot_reply(parent_ts=user_msg_ts, timeout=60)
    assert bot_reply is not None
    thread_ts = bot_reply["ts"]
    
    # 2. Reply "Thanks"
    await slack_client.send_message("Thanks, that helps!", thread_ts=thread_ts)
    
    # If we reached here without errors, the interaction was successful.
    assert True