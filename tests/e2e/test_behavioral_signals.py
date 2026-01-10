"""End-to-End tests for Behavioral Signals flow (Phase 10.5)."""

import pytest
import uuid
import asyncio
import logging
from sqlalchemy import select

from knowledge_base.db.models import BehavioralSignal, BotResponse
from knowledge_base.lifecycle.signals import (
    record_bot_response,
    process_thread_message,
    process_reaction,
    SIGNAL_SCORES,
)

logger = logging.getLogger(__name__)

# Mark all tests in this module as e2e
pytestmark = pytest.mark.e2e

@pytest.mark.asyncio
async def test_behavioral_signals_flow(db_session, e2e_config):
    """
    Scenario: Behavioral Signals
    1. Record a bot response in DB
    2. Process a "thanks" message in the thread
    3. Verify BehavioralSignal record for 'thanks'
    4. Process a positive reaction on the bot response
    5. Verify BehavioralSignal record for 'positive_reaction'
    """
    unique_id = uuid.uuid4().hex[:8]
    response_ts = f"1700000000.{unique_id}"
    thread_ts = response_ts
    user_id = "U_USER_123"
    bot_user_id = e2e_config["bot_user_id"]
    chunk_ids = [f"chunk_{unique_id}"]
    
    # 1. Record Bot Response
    await record_bot_response(
        response_ts=response_ts,
        thread_ts=thread_ts,
        channel_id=e2e_config["channel_id"],
        user_id=user_id,
        query="How do I do X?",
        response_text="To do X, you need to Y.",
        chunk_ids=chunk_ids,
    )
    
    # Verify BotResponse exists
    stmt = select(BotResponse).where(BotResponse.response_ts == response_ts)
    result = await db_session.execute(stmt)
    response = result.scalar_one_or_none()
    assert response is not None
    
    # 2. Process "thanks" message
    signal = await process_thread_message(
        thread_ts=thread_ts,
        user_id=user_id,
        text="Thanks, that's exactly what I needed!",
        bot_user_id=bot_user_id,
    )
    
    # 3. Verify Signal
    assert signal is not None
    assert signal.signal_type == "thanks"
    assert signal.signal_value == SIGNAL_SCORES["thanks"]
    
    # Verify in DB
    stmt = select(BehavioralSignal).where(
        BehavioralSignal.response_ts == response_ts,
        BehavioralSignal.signal_type == "thanks"
    )
    result = await db_session.execute(stmt)
    db_signal = result.scalar_one_or_none()
    assert db_signal is not None
    assert db_signal.slack_user_id == user_id

    # 4. Process positive reaction
    signal_reaction = await process_reaction(
        item_ts=response_ts,
        user_id=user_id,
        reaction="thumbsup",
        bot_user_id=bot_user_id,
    )
    
    # 5. Verify Reaction Signal
    assert signal_reaction is not None
    assert signal_reaction.signal_type == "positive_reaction"
    assert signal_reaction.signal_value == SIGNAL_SCORES["positive_reaction"]
    
    # Verify in DB
    stmt = select(BehavioralSignal).where(
        BehavioralSignal.response_ts == response_ts,
        BehavioralSignal.signal_type == "positive_reaction"
    )
    result = await db_session.execute(stmt)
    db_signal_reaction = result.scalar_one_or_none()
    assert db_signal_reaction is not None
    assert db_signal_reaction.reaction == "thumbsup"

@pytest.mark.asyncio
async def test_follow_up_signal(db_session, e2e_config):
    """Verify follow-up question marks the response."""
    unique_id = uuid.uuid4().hex[:8]
    response_ts = f"1700000100.{unique_id}"
    thread_ts = response_ts
    user_id = "U_USER_456"
    bot_user_id = e2e_config["bot_user_id"]
    
    await record_bot_response(
        response_ts=response_ts,
        thread_ts=thread_ts,
        channel_id=e2e_config["channel_id"],
        user_id=user_id,
        query="What is Y?",
        response_text="Y is Z.",
        chunk_ids=["chunk_y"],
    )
    
    # Process follow-up question
    signal = await process_thread_message(
        thread_ts=thread_ts,
        user_id=user_id,
        text="But what about W?",
        bot_user_id=bot_user_id,
    )
    
    assert signal is not None
    assert signal.signal_type == "follow_up"
    
    # Verify BotResponse is marked as having follow-up
    stmt = select(BotResponse).where(BotResponse.response_ts == response_ts)
    result = await db_session.execute(stmt)
    response = result.scalar_one()
    assert response.has_follow_up is True
