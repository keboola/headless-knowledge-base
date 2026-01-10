"""Behavioral signal analysis and tracking (Phase 10.5).

Detects implicit feedback from Slack interactions:
- Follow-up questions (user not satisfied)
- Gratitude expressions (user satisfied)
- Frustration expressions (user frustrated)
- Emoji reactions (quick feedback)
- Thread abandonment (satisfied silence)
"""

import json
import logging
import re
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from knowledge_base.db.database import async_session_maker
from knowledge_base.db.models import BehavioralSignal, BotResponse

logger = logging.getLogger(__name__)


# Signal score impacts (normalized to -1.0 to +1.0)
SIGNAL_SCORES = {
    "follow_up": -0.3,          # User asked another question
    "thanks": 0.4,              # User expressed gratitude
    "frustration": -0.5,        # User expressed frustration
    "positive_reaction": 0.5,   # Positive emoji reaction
    "negative_reaction": -0.5,  # Negative emoji reaction
    "satisfied_silence": 0.1,   # No follow-up after timeout
    "rephrasing": -0.4,         # User rephrased the same question
}

# Positive emoji reactions
POSITIVE_REACTIONS = {
    "thumbsup", "+1", "white_check_mark", "heavy_check_mark",
    "tada", "heart", "star", "fire", "100", "clap",
    "raised_hands", "pray", "ok_hand", "muscle",
}

# Negative emoji reactions
NEGATIVE_REACTIONS = {
    "thumbsdown", "-1", "x", "no_entry", "no_entry_sign",
    "confused", "thinking_face", "face_with_raised_eyebrow",
}


class SignalAnalyzer:
    """Analyzes text for behavioral signals."""

    # Gratitude patterns
    GRATITUDE_PATTERNS = [
        r"\bthanks?\b",
        r"\bthank\s+you\b",
        r"\bthx\b",
        r"\bhelpful\b",
        r"\bperfect\b",
        r"\bgreat\b",
        r"\bawesome\b",
        r"\bexcellent\b",
        r"\bamazing\b",
        r"\bthat('s|\s+is)\s+(exactly\s+)?what\s+i\s+(needed|wanted)\b",
        r"\bgot\s+it\b",
        r"\bmakes\s+sense\b",
        r"\bvery\s+helpful\b",
        r"\bappreciate\b",
    ]

    # Frustration patterns
    FRUSTRATION_PATTERNS = [
        r"\bnot\s+helpful\b",
        r"\bwrong\b",
        r"\bdoesn't\s+(work|help|make\s+sense)\b",
        r"\bdon't\s+understand\b",
        r"\bthat's\s+not\s+(right|correct|what)\b",
        r"\bstill\s+(don't|doesn't|can't)\b",
        r"\bconfused\b",
        r"\bfrustrat",
        r"\buseless\b",
        r"\bnot\s+what\s+i\b",
        r"\btried\s+that\b",
        r"\balready\s+(know|tried)\b",
    ]

    # Question patterns (follow-up detection)
    QUESTION_PATTERNS = [
        r"\?$",  # Ends with question mark
        r"^(what|how|why|when|where|who|which|can|could|would|should|is|are|do|does)\b",
        r"\bwhat\s+about\b",
        r"\bhow\s+do\s+i\b",
        r"\bcan\s+you\b",
        r"\bwhat\s+if\b",
        r"\bbut\s+what\b",
        r"\band\s+how\b",
    ]

    def __init__(self):
        self._gratitude_re = [re.compile(p, re.IGNORECASE) for p in self.GRATITUDE_PATTERNS]
        self._frustration_re = [re.compile(p, re.IGNORECASE) for p in self.FRUSTRATION_PATTERNS]
        self._question_re = [re.compile(p, re.IGNORECASE) for p in self.QUESTION_PATTERNS]

    def is_gratitude(self, text: str) -> bool:
        """Check if text expresses gratitude."""
        text = text.strip()
        return any(pattern.search(text) for pattern in self._gratitude_re)

    def is_frustration(self, text: str) -> bool:
        """Check if text expresses frustration."""
        text = text.strip()
        return any(pattern.search(text) for pattern in self._frustration_re)

    def is_follow_up_question(self, text: str) -> bool:
        """Check if text is a follow-up question."""
        text = text.strip()
        # Short messages with question marks are likely follow-ups
        if len(text) < 100 and "?" in text:
            return True
        return any(pattern.search(text) for pattern in self._question_re)

    def is_similar_query(
        self, query1: str, query2: str, threshold: float = 0.6
    ) -> bool:
        """Check if two queries are similar (rephrasing)."""
        # Simple word overlap check
        words1 = set(query1.lower().split())
        words2 = set(query2.lower().split())

        # Remove common words
        stopwords = {"the", "a", "an", "is", "are", "was", "were", "to", "for", "of", "in", "on", "at", "it", "i", "my", "me"}
        words1 = words1 - stopwords
        words2 = words2 - stopwords

        if not words1 or not words2:
            return False

        overlap = len(words1 & words2)
        total = len(words1 | words2)

        if total == 0:
            return False

        similarity = overlap / total
        return similarity >= threshold

    def analyze_message(self, text: str) -> tuple[str | None, float]:
        """Analyze a message and return signal type and score.

        Returns:
            Tuple of (signal_type, score) or (None, 0) if no signal detected
        """
        # Check frustration first (takes priority)
        if self.is_frustration(text):
            return "frustration", SIGNAL_SCORES["frustration"]

        # Check gratitude
        if self.is_gratitude(text):
            return "thanks", SIGNAL_SCORES["thanks"]

        # Check if it's a follow-up question
        if self.is_follow_up_question(text):
            return "follow_up", SIGNAL_SCORES["follow_up"]

        return None, 0.0

    def is_positive_reaction(self, reaction: str) -> bool:
        """Check if emoji reaction is positive."""
        return reaction.lower() in POSITIVE_REACTIONS

    def is_negative_reaction(self, reaction: str) -> bool:
        """Check if emoji reaction is negative."""
        return reaction.lower() in NEGATIVE_REACTIONS


# Global analyzer instance
_analyzer = SignalAnalyzer()


def get_signal_analyzer() -> SignalAnalyzer:
    """Get the signal analyzer instance."""
    return _analyzer


async def record_bot_response(
    response_ts: str,
    thread_ts: str,
    channel_id: str,
    user_id: str,
    query: str,
    response_text: str,
    chunk_ids: list[str],
) -> BotResponse:
    """Record a bot response for behavioral tracking."""
    async with async_session_maker() as session:
        response = BotResponse(
            response_ts=response_ts,
            thread_ts=thread_ts,
            channel_id=channel_id,
            user_id=user_id,
            query=query,
            response_text=response_text[:2000],  # Truncate if too long
            chunk_ids=json.dumps(chunk_ids),
        )
        session.add(response)
        await session.commit()
        await session.refresh(response)

        logger.debug(f"Recorded bot response: ts={response_ts}, chunks={len(chunk_ids)}")
        return response


async def get_response_for_thread(thread_ts: str) -> BotResponse | None:
    """Get the most recent bot response for a thread."""
    async with async_session_maker() as session:
        result = await session.execute(
            select(BotResponse)
            .where(BotResponse.thread_ts == thread_ts)
            .order_by(BotResponse.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


async def get_response_by_ts(response_ts: str) -> BotResponse | None:
    """Get a bot response by its message timestamp."""
    async with async_session_maker() as session:
        result = await session.execute(
            select(BotResponse).where(BotResponse.response_ts == response_ts)
        )
        return result.scalar_one_or_none()


async def record_signal(
    response_ts: str,
    thread_ts: str,
    chunk_ids: list[str],
    user_id: str,
    signal_type: str,
    signal_value: float,
    raw_text: str | None = None,
    reaction: str | None = None,
) -> BehavioralSignal:
    """Record a behavioral signal."""
    async with async_session_maker() as session:
        signal = BehavioralSignal(
            response_ts=response_ts,
            thread_ts=thread_ts,
            chunk_ids=json.dumps(chunk_ids),
            slack_user_id=user_id,
            signal_type=signal_type,
            signal_value=signal_value,
            raw_text=raw_text[:1000] if raw_text else None,
            reaction=reaction,
        )
        session.add(signal)
        await session.commit()
        await session.refresh(signal)

        logger.info(
            f"Recorded signal: type={signal_type}, value={signal_value}, "
            f"user={user_id}, chunks={len(chunk_ids)}"
        )
        return signal


async def process_thread_message(
    thread_ts: str,
    user_id: str,
    text: str,
    bot_user_id: str,
) -> BehavioralSignal | None:
    """Process a message in a thread for behavioral signals.

    Args:
        thread_ts: Thread timestamp
        user_id: User who sent the message
        text: Message text
        bot_user_id: Bot's user ID (to ignore bot messages)

    Returns:
        BehavioralSignal if a signal was detected, None otherwise
    """
    # Ignore bot's own messages
    if user_id == bot_user_id:
        return None

    # Get the bot response for this thread
    response = await get_response_for_thread(thread_ts)
    if not response:
        return None

    # Analyze the message
    analyzer = get_signal_analyzer()
    signal_type, signal_value = analyzer.analyze_message(text)

    if signal_type:
        chunk_ids = json.loads(response.chunk_ids) if response.chunk_ids else []

        # Mark response as having a follow-up
        if signal_type == "follow_up":
            async with async_session_maker() as session:
                result = await session.execute(
                    select(BotResponse).where(BotResponse.response_ts == response.response_ts)
                )
                db_response = result.scalar_one_or_none()
                if db_response:
                    db_response.has_follow_up = True
                    await session.commit()

        return await record_signal(
            response_ts=response.response_ts,
            thread_ts=thread_ts,
            chunk_ids=chunk_ids,
            user_id=user_id,
            signal_type=signal_type,
            signal_value=signal_value,
            raw_text=text,
        )

    return None


async def process_reaction(
    item_ts: str,
    user_id: str,
    reaction: str,
    bot_user_id: str,
) -> BehavioralSignal | None:
    """Process an emoji reaction on a bot message.

    Args:
        item_ts: Timestamp of the message that was reacted to
        user_id: User who added the reaction
        reaction: Emoji name
        bot_user_id: Bot's user ID

    Returns:
        BehavioralSignal if a signal was detected, None otherwise
    """
    # Ignore bot's own reactions
    if user_id == bot_user_id:
        return None

    # Get the bot response
    response = await get_response_by_ts(item_ts)
    if not response:
        return None

    analyzer = get_signal_analyzer()
    chunk_ids = json.loads(response.chunk_ids) if response.chunk_ids else []

    if analyzer.is_positive_reaction(reaction):
        return await record_signal(
            response_ts=response.response_ts,
            thread_ts=response.thread_ts,
            chunk_ids=chunk_ids,
            user_id=user_id,
            signal_type="positive_reaction",
            signal_value=SIGNAL_SCORES["positive_reaction"],
            reaction=reaction,
        )

    elif analyzer.is_negative_reaction(reaction):
        return await record_signal(
            response_ts=response.response_ts,
            thread_ts=response.thread_ts,
            chunk_ids=chunk_ids,
            user_id=user_id,
            signal_type="negative_reaction",
            signal_value=SIGNAL_SCORES["negative_reaction"],
            reaction=reaction,
        )

    return None


async def get_signals_for_chunks(chunk_ids: list[str]) -> list[BehavioralSignal]:
    """Get all behavioral signals for a list of chunks."""
    if not chunk_ids:
        return []

    async with async_session_maker() as session:
        # We need to search within JSON arrays, so use LIKE for simplicity
        # This is not efficient for large datasets, but works for now
        conditions = []
        for chunk_id in chunk_ids:
            conditions.append(BehavioralSignal.chunk_ids.contains(chunk_id))

        from sqlalchemy import or_

        result = await session.execute(
            select(BehavioralSignal)
            .where(or_(*conditions))
            .order_by(BehavioralSignal.created_at.desc())
        )
        return list(result.scalars().all())


async def get_signal_stats() -> dict[str, Any]:
    """Get statistics about behavioral signals."""
    from sqlalchemy import func

    async with async_session_maker() as session:
        # Total signals
        total_result = await session.execute(
            select(func.count(BehavioralSignal.id))
        )
        total = total_result.scalar() or 0

        # By type
        type_result = await session.execute(
            select(
                BehavioralSignal.signal_type,
                func.count(BehavioralSignal.id),
                func.avg(BehavioralSignal.signal_value),
            ).group_by(BehavioralSignal.signal_type)
        )
        by_type = {
            row[0]: {"count": row[1], "avg_value": round(row[2], 3) if row[2] else 0}
            for row in type_result.fetchall()
        }

        # Recent (last 7 days)
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(days=7)
        recent_result = await session.execute(
            select(func.count(BehavioralSignal.id)).where(
                BehavioralSignal.created_at >= cutoff
            )
        )
        recent = recent_result.scalar() or 0

        # Total bot responses tracked
        responses_result = await session.execute(
            select(func.count(BotResponse.id))
        )
        total_responses = responses_result.scalar() or 0

        return {
            "total_signals": total,
            "signals_last_7_days": recent,
            "total_responses_tracked": total_responses,
            "by_type": by_type,
        }
