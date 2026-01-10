"""Content owner notification for feedback (Phase 10.6).

Notifies content owners when their content receives negative feedback.
Falls back to admin channel if owner cannot be identified or notified.

Owner information is read from ChromaDB metadata (source of truth).
"""

import logging
from typing import Any

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from sqlalchemy import select

from knowledge_base.config import settings
from knowledge_base.db.database import async_session_maker
from knowledge_base.db.models import BotResponse
from knowledge_base.vectorstore.client import ChromaClient

logger = logging.getLogger(__name__)

# Singleton ChromaDB client
_chroma_client: ChromaClient | None = None


def get_chroma_client() -> ChromaClient:
    """Get or create a ChromaDB client instance."""
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = ChromaClient()
    return _chroma_client

# Admin channel fallback
ADMIN_CHANNEL = getattr(settings, "KNOWLEDGE_ADMIN_CHANNEL", "#knowledge-admins")


async def notify_content_owner(
    client: WebClient,
    chunk_ids: list[str],
    feedback_type: str,
    issue_description: str,
    suggested_correction: str | None,
    reporter_id: str,
    channel_id: str,
    message_ts: str,
) -> bool:
    """Notify content owner about feedback. Falls back to admin channel.

    Args:
        client: Slack WebClient
        chunk_ids: List of chunk IDs from the response
        feedback_type: Type of feedback (incorrect, outdated, confusing)
        issue_description: What the user reported as the issue
        suggested_correction: User's suggested fix (if provided)
        reporter_id: Slack user ID of reporter
        channel_id: Channel where feedback originated
        message_ts: Original message timestamp

    Returns:
        True if owner was notified, False if fell back to admin channel
    """
    # 1. Get owner email from chunk's governance metadata
    owner_email = await get_owner_email_for_chunks(chunk_ids)

    # 2. Get additional context
    context = await _get_feedback_context(message_ts, chunk_ids)

    if owner_email:
        # 3. Lookup Slack user by email
        owner_slack_id = await lookup_slack_user_by_email(client, owner_email)

        if owner_slack_id:
            # 4. Send DM to owner
            success = await send_owner_dm(
                client=client,
                owner_slack_id=owner_slack_id,
                feedback_type=feedback_type,
                issue_description=issue_description,
                suggested_correction=suggested_correction,
                reporter_id=reporter_id,
                channel_id=channel_id,
                message_ts=message_ts,
                context=context,
            )
            if success:
                logger.info(f"Notified owner {owner_email} ({owner_slack_id}) about {feedback_type} feedback")
                return True

    # 5. Fallback: send to admin channel
    logger.info(f"Falling back to admin channel for {feedback_type} feedback (no owner or lookup failed)")
    await send_to_admin_channel(
        client=client,
        feedback_type=feedback_type,
        issue_description=issue_description,
        suggested_correction=suggested_correction,
        reporter_id=reporter_id,
        channel_id=channel_id,
        message_ts=message_ts,
        context=context,
        owner_email=owner_email,
    )
    return False


async def get_owner_email_for_chunks(chunk_ids: list[str]) -> str | None:
    """Get owner email from ChromaDB metadata for chunks.

    Owner is stored in ChromaDB metadata (source of truth).

    Args:
        chunk_ids: List of chunk IDs to look up

    Returns:
        Owner email if found, None otherwise
    """
    if not chunk_ids:
        return None

    try:
        chroma = get_chroma_client()
        metadata = await chroma.get_metadata(chunk_ids)

        # Find the first chunk with an owner
        for chunk_id in chunk_ids:
            if chunk_id in metadata:
                owner = metadata[chunk_id].get("owner", "")
                if owner:
                    return owner

        return None

    except Exception as e:
        logger.warning(f"Failed to get owner from ChromaDB: {e}")
        return None


async def lookup_slack_user_by_email(client: WebClient, email: str) -> str | None:
    """Lookup Slack user ID by email address.

    Args:
        client: Slack WebClient
        email: Email address to lookup

    Returns:
        Slack user ID if found, None otherwise
    """
    try:
        result = client.users_lookupByEmail(email=email)
        if result.get("ok") and result.get("user"):
            return result["user"]["id"]
    except SlackApiError as e:
        if e.response.get("error") == "users_not_found":
            logger.warning(f"No Slack user found for email: {email}")
        else:
            logger.error(f"Slack API error looking up user by email: {e}")
    except Exception as e:
        logger.error(f"Error looking up Slack user by email: {e}")

    return None


async def send_owner_dm(
    client: WebClient,
    owner_slack_id: str,
    feedback_type: str,
    issue_description: str,
    suggested_correction: str | None,
    reporter_id: str,
    channel_id: str,
    message_ts: str,
    context: dict[str, Any],
) -> bool:
    """Send DM to content owner about feedback.

    Args:
        client: Slack WebClient
        owner_slack_id: Owner's Slack user ID
        feedback_type: Type of feedback
        issue_description: What was reported
        suggested_correction: Suggested fix
        reporter_id: Who reported it
        channel_id: Where it was reported
        message_ts: Original message timestamp
        context: Additional context (query, response, source titles)

    Returns:
        True if DM was sent successfully
    """
    blocks = build_owner_notification_blocks(
        feedback_type=feedback_type,
        issue_description=issue_description,
        suggested_correction=suggested_correction,
        reporter_id=reporter_id,
        channel_id=channel_id,
        message_ts=message_ts,
        context=context,
    )

    try:
        client.chat_postMessage(
            channel=owner_slack_id,  # DM by sending to user ID
            blocks=blocks,
            text=f"Your content received {feedback_type} feedback",
        )
        return True
    except SlackApiError as e:
        logger.error(f"Failed to send DM to owner {owner_slack_id}: {e}")
        return False


async def send_to_admin_channel(
    client: WebClient,
    feedback_type: str,
    issue_description: str,
    suggested_correction: str | None,
    reporter_id: str,
    channel_id: str,
    message_ts: str,
    context: dict[str, Any],
    owner_email: str | None = None,
) -> bool:
    """Send feedback notification to admin channel.

    Args:
        client: Slack WebClient
        feedback_type: Type of feedback
        issue_description: What was reported
        suggested_correction: Suggested fix
        reporter_id: Who reported it
        channel_id: Where it was reported
        message_ts: Original message timestamp
        context: Additional context
        owner_email: Owner email if known (for context)

    Returns:
        True if message was sent successfully
    """
    admin_channel_id = await _get_admin_channel_id(client)
    if not admin_channel_id:
        logger.error(f"Admin channel {ADMIN_CHANNEL} not found")
        return False

    blocks = build_admin_notification_blocks(
        feedback_type=feedback_type,
        issue_description=issue_description,
        suggested_correction=suggested_correction,
        reporter_id=reporter_id,
        channel_id=channel_id,
        message_ts=message_ts,
        context=context,
        owner_email=owner_email,
    )

    try:
        client.chat_postMessage(
            channel=admin_channel_id,
            blocks=blocks,
            text=f"Knowledge feedback: {feedback_type} from <@{reporter_id}>",
        )
        return True
    except SlackApiError as e:
        logger.error(f"Failed to send to admin channel: {e}")
        return False


def build_owner_notification_blocks(
    feedback_type: str,
    issue_description: str,
    suggested_correction: str | None,
    reporter_id: str,
    channel_id: str,
    message_ts: str,
    context: dict[str, Any],
) -> list[dict]:
    """Build rich notification blocks for content owner DM.

    Args:
        feedback_type: Type of feedback
        issue_description: What was reported
        suggested_correction: Suggested fix
        reporter_id: Who reported it
        channel_id: Where it was reported
        message_ts: Original message timestamp
        context: Additional context

    Returns:
        List of Slack blocks
    """
    feedback_emoji = {
        "incorrect": ":x:",
        "outdated": ":hourglass:",
        "confusing": ":thinking_face:",
    }
    emoji = feedback_emoji.get(feedback_type, ":warning:")

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} Feedback on Your Content",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"Someone reported an issue with content you own.\n\n"
                f"*Issue Type:* {feedback_type.title()}\n"
                f"*Reported by:* <@{reporter_id}>",
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*What was reported:*\n>{issue_description}",
            },
        },
    ]

    # Add suggested correction if provided
    if suggested_correction:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Suggested correction:*\n>{suggested_correction}",
            },
        })

    # Add original question if available
    if context.get("query"):
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Original question:*\n>{context['query']}",
            },
        })

    # Add source document info
    if context.get("source_titles"):
        sources = "\n".join(f"• {title}" for title in context["source_titles"][:3])
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Affected content:*\n{sources}",
            },
        })

    # Add thread link
    thread_link = f"https://slack.com/archives/{channel_id}/p{message_ts.replace('.', '')}"
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*View conversation:* <{thread_link}|Open thread>",
        },
    })

    blocks.append({"type": "divider"})

    # Add action buttons
    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "View Thread", "emoji": True},
                "url": thread_link,
                "action_id": "view_feedback_thread",
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Acknowledge", "emoji": True},
                "style": "primary",
                "action_id": f"ack_feedback_{message_ts}",
            },
        ],
    })

    return blocks


def build_admin_notification_blocks(
    feedback_type: str,
    issue_description: str,
    suggested_correction: str | None,
    reporter_id: str,
    channel_id: str,
    message_ts: str,
    context: dict[str, Any],
    owner_email: str | None = None,
) -> list[dict]:
    """Build notification blocks for admin channel.

    Similar to owner notification but includes reason for escalation.
    """
    feedback_emoji = {
        "incorrect": ":x:",
        "outdated": ":hourglass:",
        "confusing": ":thinking_face:",
    }
    emoji = feedback_emoji.get(feedback_type, ":warning:")

    # Explain why it went to admin channel
    if owner_email:
        escalation_reason = f"Owner ({owner_email}) could not be found in Slack"
    else:
        escalation_reason = "No owner assigned to this content"

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} Knowledge Feedback (No Owner)",
                "emoji": True,
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"_Escalated to admins: {escalation_reason}_",
                }
            ],
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*Issue Type:*\n{feedback_type.title()}",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Reported by:*\n<@{reporter_id}>",
                },
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Issue description:*\n>{issue_description}",
            },
        },
    ]

    if suggested_correction:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Suggested correction:*\n>{suggested_correction}",
            },
        })

    if context.get("query"):
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Original question:*\n>{context['query']}",
            },
        })

    if context.get("source_titles"):
        sources = "\n".join(f"• {title}" for title in context["source_titles"][:3])
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Affected content:*\n{sources}",
            },
        })

    thread_link = f"https://slack.com/archives/{channel_id}/p{message_ts.replace('.', '')}"
    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "View Thread", "emoji": True},
                "url": thread_link,
                "action_id": "view_feedback_thread",
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Mark Resolved", "emoji": True},
                "style": "primary",
                "action_id": f"resolve_feedback_{message_ts}",
            },
        ],
    })

    return blocks


async def _get_feedback_context(message_ts: str, chunk_ids: list[str]) -> dict[str, Any]:
    """Get context for the feedback from database.

    Bot response comes from SQLite/DuckDB (analytics).
    Source titles come from ChromaDB metadata (source of truth).

    Args:
        message_ts: Original message timestamp
        chunk_ids: List of chunk IDs

    Returns:
        Dict with query, response, source_titles
    """
    context: dict[str, Any] = {
        "query": None,
        "response": None,
        "source_titles": [],
    }

    # Get bot response from SQLite/DuckDB (analytics data)
    async with async_session_maker() as session:
        if message_ts:
            stmt = select(BotResponse).where(BotResponse.response_ts == message_ts)
            result = await session.execute(stmt)
            bot_response = result.scalar_one_or_none()

            if bot_response:
                context["query"] = bot_response.query
                context["response"] = bot_response.response_text

    # Get source titles from ChromaDB metadata (source of truth)
    if chunk_ids:
        try:
            chroma = get_chroma_client()
            metadata = await chroma.get_metadata(chunk_ids)

            seen_titles = set()
            for chunk_id in chunk_ids:
                if chunk_id in metadata:
                    title = metadata[chunk_id].get("page_title", "")
                    if title and title not in seen_titles:
                        context["source_titles"].append(title)
                        seen_titles.add(title)
        except Exception as e:
            logger.warning(f"Failed to get source titles from ChromaDB: {e}")

    return context


async def _get_admin_channel_id(client: WebClient) -> str | None:
    """Find the admin channel ID.

    Args:
        client: Slack WebClient

    Returns:
        Channel ID if found, None otherwise
    """
    channel_name = ADMIN_CHANNEL.lstrip("#")

    try:
        result = client.conversations_list(types="public_channel,private_channel")

        for channel in result.get("channels", []):
            if channel.get("name") == channel_name:
                return channel["id"]

        logger.warning(f"Admin channel {ADMIN_CHANNEL} not found")
        return None

    except SlackApiError as e:
        logger.error(f"Failed to find admin channel: {e}")
        return None


async def confirm_feedback_to_reporter(
    client: WebClient,
    channel_id: str,
    reporter_id: str,
    feedback_type: str,
    owner_notified: bool,
) -> None:
    """Send confirmation to reporter that feedback was received.

    Args:
        client: Slack WebClient
        channel_id: Channel to send confirmation
        reporter_id: User who reported the issue
        feedback_type: Type of feedback submitted
        owner_notified: Whether owner was notified (vs admin channel)
    """
    if owner_notified:
        message = (
            f"Thanks for your feedback! The content owner has been notified "
            f"and will review the {feedback_type} report."
        )
    else:
        message = (
            f"Thanks for your feedback! The knowledge admins have been notified "
            f"and will review the {feedback_type} report."
        )

    try:
        client.chat_postEphemeral(
            channel=channel_id,
            user=reporter_id,
            text=message,
        )
    except SlackApiError as e:
        logger.error(f"Failed to confirm feedback to reporter: {e}")
