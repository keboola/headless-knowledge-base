"""Admin escalation for negative feedback on knowledge base content.

Chunk data is retrieved from ChromaDB (source of truth).
BotResponse and UserFeedback are stored in database for analytics.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from slack_sdk import WebClient
from sqlalchemy import func, select

from knowledge_base.config import settings
from knowledge_base.db.database import async_session_maker
# BotResponse and UserFeedback are analytics models kept in database
from knowledge_base.db.models import BotResponse, UserFeedback
from knowledge_base.vectorstore.client import ChromaClient

logger = logging.getLogger(__name__)

# Configuration
ADMIN_CHANNEL = getattr(settings, "KNOWLEDGE_ADMIN_CHANNEL", "#knowledge-admins")
AUTO_ESCALATE_THRESHOLD = 3  # Auto-notify admins after this many negative reports
ESCALATE_WINDOW_HOURS = 24  # Within this time window


async def offer_admin_help(
    client: WebClient,
    channel_id: str,
    user_id: str,
    message_ts: str,
    feedback_type: str,
    chunk_ids: list[str],
) -> None:
    """Offer to escalate to knowledge admin after negative feedback.

    Called after user provides negative feedback (outdated, incorrect, confusing).
    Shows a button to request admin help.
    """
    if feedback_type == "helpful":
        return  # No escalation for positive feedback

    # Build the offer message
    feedback_labels = {
        "outdated": "outdated",
        "incorrect": "incorrect",
        "confusing": "confusing",
    }

    label = feedback_labels.get(feedback_type, feedback_type)

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"Thanks for flagging this as *{label}*! Your feedback helps improve the knowledge base.\n\n"
                    f"_Would you like to notify a knowledge admin to help correct this information?_"
                ),
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Yes, get admin help",
                        "emoji": True,
                    },
                    "style": "primary",
                    "action_id": f"escalate_to_admin_{message_ts}",
                    "value": json.dumps({
                        "message_ts": message_ts,
                        "feedback_type": feedback_type,
                        "chunk_ids": chunk_ids,
                        "channel_id": channel_id,
                        "reporter_id": user_id,
                    }),
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "No thanks",
                        "emoji": True,
                    },
                    "action_id": f"dismiss_escalation_{message_ts}",
                },
            ],
        },
    ]

    try:
        await client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            blocks=blocks,
            text="Would you like to notify a knowledge admin?",
        )
    except Exception as e:
        logger.error(f"Failed to offer admin help: {e}")


async def handle_escalate_to_admin(ack: Any, body: dict, client: WebClient) -> None:
    """Handle user clicking 'Yes, get admin help' button."""
    await ack()

    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]
    action = body["actions"][0]

    try:
        data = json.loads(action.get("value", "{}"))
    except json.JSONDecodeError:
        data = {}

    message_ts = data.get("message_ts")
    feedback_type = data.get("feedback_type", "unknown")
    chunk_ids = data.get("chunk_ids", [])
    original_channel = data.get("channel_id", channel_id)
    reporter_id = data.get("reporter_id", user_id)

    # Get context from bot response
    context = await _get_escalation_context(message_ts, chunk_ids)

    # Build admin notification
    blocks = _build_admin_notification(
        reporter_id=reporter_id,
        feedback_type=feedback_type,
        context=context,
        original_channel=original_channel,
        message_ts=message_ts,
    )

    # Send to admin channel
    try:
        # Try to find or create admin channel
        admin_channel = await _get_admin_channel(client)

        if admin_channel:
            await client.chat_postMessage(
                channel=admin_channel,
                blocks=blocks,
                text=f"Knowledge feedback escalation from <@{reporter_id}>",
            )

            # Confirm to user
            await client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=(
                    f"Knowledge admins have been notified in {ADMIN_CHANNEL}.\n"
                    f"They'll review the feedback and update the content. Thank you!"
                ),
            )
        else:
            # Fallback: post in same channel
            await client.chat_postMessage(
                channel=original_channel,
                thread_ts=message_ts,
                blocks=blocks,
                text=f"Knowledge feedback escalation from <@{reporter_id}>",
            )

            await client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text="Escalation posted in the thread. An admin will review soon.",
            )

    except Exception as e:
        logger.error(f"Failed to escalate to admin: {e}")
        await client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=f"Sorry, couldn't notify admins. Please post in {ADMIN_CHANNEL} manually.",
        )


async def handle_dismiss_escalation(ack: Any, body: dict, client: WebClient) -> None:
    """Handle user clicking 'No thanks' button."""
    await ack()

    # Just acknowledge - the ephemeral message will disappear
    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]

    await client.chat_postEphemeral(
        channel=channel_id,
        user=user_id,
        text="No problem! Your feedback has still been recorded. Thanks!",
    )


async def check_auto_escalation(
    chunk_id: str,
    feedback_type: str,
    client: WebClient,
    channel_id: str,
) -> bool:
    """Check if we should auto-escalate based on feedback threshold.

    Returns True if auto-escalation was triggered.
    """
    if feedback_type == "helpful":
        return False

    async with async_session_maker() as session:
        # Count recent negative feedback for this chunk
        cutoff = datetime.utcnow() - timedelta(hours=ESCALATE_WINDOW_HOURS)

        stmt = (
            select(func.count(UserFeedback.id))
            .where(UserFeedback.chunk_id == chunk_id)
            .where(UserFeedback.feedback_type.in_(["outdated", "incorrect", "confusing"]))
            .where(UserFeedback.created_at >= cutoff)
        )

        result = await session.execute(stmt)
        count = result.scalar() or 0

        if count >= AUTO_ESCALATE_THRESHOLD:
            # Check if we already escalated (could add a flag)
            logger.info(f"Auto-escalating chunk {chunk_id} after {count} negative reports")

            # Get chunk info from ChromaDB (source of truth)
            chroma = ChromaClient()
            chroma_result = await chroma.get(ids=[chunk_id])

            if chroma_result.get("ids"):
                documents = chroma_result.get("documents", [])
                metadatas = chroma_result.get("metadatas", [])

                chunk_info = {
                    "chunk_id": chunk_id,
                    "content": documents[0] if documents else "",
                    "page_title": metadatas[0].get("page_title", "") if metadatas else "",
                }

                await _auto_notify_admins(
                    client=client,
                    chunk_info=chunk_info,
                    negative_count=count,
                    channel_id=channel_id,
                )
                return True

    return False


async def _get_escalation_context(message_ts: str, chunk_ids: list[str]) -> dict:
    """Get context for the escalation.

    Bot response from database, chunk metadata from ChromaDB.
    """
    context = {
        "query": None,
        "response": None,
        "source_titles": [],
        "source_urls": [],
    }

    async with async_session_maker() as session:
        # Get bot response from database (analytics table)
        if message_ts:
            stmt = select(BotResponse).where(BotResponse.response_ts == message_ts)
            result = await session.execute(stmt)
            bot_response = result.scalar_one_or_none()

            if bot_response:
                context["query"] = bot_response.query
                context["response"] = bot_response.response_text

    # Get chunk sources from ChromaDB (source of truth)
    if chunk_ids:
        chroma = ChromaClient()
        chroma_result = await chroma.get(ids=chunk_ids)

        for i, chunk_id in enumerate(chroma_result.get("ids", [])):
            metadatas = chroma_result.get("metadatas", [])
            if metadatas and i < len(metadatas):
                page_title = metadatas[i].get("page_title", "")
                url = metadatas[i].get("url", "")
                if page_title:
                    context["source_titles"].append(page_title)
                    context["source_urls"].append(url)

    return context


def _build_admin_notification(
    reporter_id: str,
    feedback_type: str,
    context: dict,
    original_channel: str,
    message_ts: str,
) -> list[dict]:
    """Build notification blocks for admin channel."""
    feedback_emoji = {
        "outdated": ":hourglass:",
        "incorrect": ":x:",
        "confusing": ":question:",
    }

    emoji = feedback_emoji.get(feedback_type, ":warning:")

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} Knowledge Feedback Escalation",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*Reported by:*\n<@{reporter_id}>",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Issue type:*\n{feedback_type.title()}",
                },
            ],
        },
    ]

    # Add context if available
    if context.get("query"):
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Original question:*\n>{context['query']}",
            },
        })

    if context.get("response"):
        response_preview = context["response"][:500]
        if len(context["response"]) > 500:
            response_preview += "..."

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Bot's response:*\n```{response_preview}```",
            },
        })

    if context.get("source_titles"):
        sources = "\n".join([
            f"• <{url}|{title}>" if url else f"• {title}"
            for title, url in zip(context["source_titles"], context["source_urls"])
        ])
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Sources used:*\n{sources}",
            },
        })

    # Thread link
    if message_ts and original_channel:
        thread_link = f"https://slack.com/archives/{original_channel}/p{message_ts.replace('.', '')}"
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Thread:* <{thread_link}|View conversation>",
            },
        })

    blocks.append({"type": "divider"})

    # Action buttons
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": "*Actions:*",
        },
    })

    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "View Thread",
                    "emoji": True,
                },
                "url": f"https://slack.com/archives/{original_channel}/p{message_ts.replace('.', '')}",
                "action_id": "view_escalation_thread",
            },
            {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "Mark Resolved",
                    "emoji": True,
                },
                "style": "primary",
                "action_id": f"resolve_escalation_{message_ts}",
            },
        ],
    })

    return blocks


async def _auto_notify_admins(
    client: WebClient,
    chunk_info: dict,
    negative_count: int,
    channel_id: str,
) -> None:
    """Send auto-escalation notification to admins.

    Args:
        client: Slack WebClient
        chunk_info: Dict with chunk_id, content, page_title from ChromaDB
        negative_count: Number of negative feedback reports
        channel_id: Fallback channel if admin channel not found
    """
    admin_channel = await _get_admin_channel(client)

    content = chunk_info.get("content", "")
    page_title = chunk_info.get("page_title", "Unknown")
    chunk_id = chunk_info.get("chunk_id", "unknown")

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": ":rotating_light: Auto-Escalation: Content Quality Alert",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*{negative_count} users* have reported issues with this content "
                    f"in the last {ESCALATE_WINDOW_HOURS} hours.\n\n"
                    f"*Content:*\n```{content[:300]}{'...' if len(content) > 300 else ''}```"
                ),
            },
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*Page:*\n{page_title}",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Chunk ID:*\n`{chunk_id}`",
                },
            ],
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "_This content may need to be updated or removed._",
                },
            ],
        },
    ]

    target_channel = admin_channel or channel_id

    try:
        await client.chat_postMessage(
            channel=target_channel,
            blocks=blocks,
            text=f"Auto-escalation: {negative_count} negative reports on content",
        )
    except Exception as e:
        logger.error(f"Failed to send auto-escalation: {e}")


async def _get_admin_channel(client: WebClient) -> str | None:
    """Find the admin channel ID.

    Supports both channel names (e.g., "#knowledge-admins") and
    channel IDs (e.g., "C0A6WU7EFMY").
    """
    # Remove # if present
    channel_value = ADMIN_CHANNEL.lstrip("#")

    # If it looks like a channel ID (starts with C), use it directly
    if channel_value.startswith("C"):
        return channel_value

    try:
        # Try to find channel by name
        result = client.conversations_list(types="public_channel,private_channel")

        for channel in result.get("channels", []):
            if channel.get("name") == channel_value:
                return channel["id"]

        # Channel not found - could create it or return None
        logger.warning(f"Admin channel {ADMIN_CHANNEL} not found")
        return None

    except Exception as e:
        logger.error(f"Failed to find admin channel: {e}")
        return None


async def handle_resolve_escalation(ack: Any, body: dict, client: WebClient) -> None:
    """Handle admin clicking 'Mark Resolved' button."""
    await ack()

    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]
    message_ts = body["message"]["ts"]

    try:
        # Update the message to show resolved
        await client.chat_update(
            channel=channel_id,
            ts=message_ts,
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f":white_check_mark: *Resolved* by <@{user_id}> at <!date^{int(datetime.utcnow().timestamp())}^{{date_short_pretty}} {{time}}|now>",
                    },
                },
            ],
            text="Escalation resolved",
        )
    except Exception as e:
        logger.error(f"Failed to mark escalation resolved: {e}")


def register_escalation_handlers(app):
    """Register admin escalation action handlers."""
    import re

    app.action(re.compile(r"escalate_to_admin_.*"))(handle_escalate_to_admin)
    app.action(re.compile(r"dismiss_escalation_.*"))(handle_dismiss_escalation)
    app.action(re.compile(r"resolve_escalation_.*"))(handle_resolve_escalation)
    app.action("view_escalation_thread")(lambda ack, body, client: ack())  # Just acknowledge URL button
