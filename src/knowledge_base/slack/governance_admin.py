"""Admin Slack interface for knowledge governance.

Posts approval/review notifications to #knowledge-admins and handles
button clicks for approve/reject/revert actions.

Follows the same patterns as admin_escalation.py for Slack Block Kit
message construction and action handler registration.
"""

import json
import logging
import re
from datetime import datetime
from typing import Any

from slack_sdk import WebClient

from knowledge_base.config import settings
from knowledge_base.db.models import KnowledgeGovernanceRecord

logger = logging.getLogger(__name__)


def _get_admin_channel() -> str:
    """Return the admin channel ID or name from settings.

    Supports both channel IDs (e.g., 'C0A6WU7EFMY') and names
    (e.g., '#knowledge-admins').
    """
    channel_value = settings.KNOWLEDGE_ADMIN_CHANNEL.lstrip("#")
    return channel_value


def _is_admin_channel(channel_id: str) -> bool:
    """Check if the given channel ID matches the configured admin channel.

    Compares against settings.KNOWLEDGE_ADMIN_CHANNEL (stripped of #).
    """
    return channel_id == _get_admin_channel()


async def _reject_non_admin(client: WebClient, channel_id: str, user_id: str) -> bool:
    """If the action did not originate from the admin channel, post ephemeral and return True.

    Returns True if the action should be rejected, False if it's from the admin channel.
    """
    if _is_admin_channel(channel_id):
        return False

    await client.chat_postEphemeral(
        channel=channel_id,
        user=user_id,
        text="Governance actions can only be performed from the admin channel.",
    )
    return True


def _format_risk_factors(risk_factors_json: str) -> str:
    """Parse risk_factors JSON and format as readable bullet list."""
    try:
        factors = json.loads(risk_factors_json)
    except (json.JSONDecodeError, TypeError) as e:
        logger.debug(f"Failed to parse risk_factors JSON: {e}")
        return "_No risk factors available_"

    if not factors:
        return "_No risk factors available_"

    # Map category slugs to human-readable labels for display
    _category_labels = {
        "routine_info": "Routine Info",
        "team_update": "Team Update",
        "process_change": "Process Change",
        "tool_technology": "Tool/Technology",
        "org_structure": "Org Structure",
        "policy_change": "Policy Change",
        "financial_impact": "Financial Impact",
        "security_change": "Security Change",
    }

    lines = []
    for factor_name, factor_value in factors.items():
        # content_impact_category is a string label, not a numeric score
        if factor_name == "content_impact_category":
            label = _category_labels.get(factor_value, str(factor_value).replace("_", " ").title())
            lines.append(f"  - Impact Category: {label}")
            continue
        label = factor_name.replace("_", " ").title()
        lines.append(f"  - {label}: {factor_value:.0f}/100")
    return "\n".join(lines)


async def notify_admin_high_risk(
    client: WebClient,
    record: KnowledgeGovernanceRecord,
) -> str | None:
    """Post approval request to #knowledge-admins for HIGH risk content.

    Returns the message timestamp (ts) for tracking, or None on failure.
    """
    admin_channel = _get_admin_channel()

    content_preview = (record.content_preview or "")[:300]
    if len(record.content_preview or "") > 300:
        content_preview += "..."

    risk_factors_text = _format_risk_factors(record.risk_factors)

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "Knowledge Approval Request",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*Risk Score:*\n{record.risk_score:.0f}/100",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Risk Tier:*\n{record.risk_tier.upper()}",
                },
            ],
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*Intake Path:*\n{record.intake_path}",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Submitted By:*\n{record.submitted_by}",
                },
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Content Preview:*\n```{content_preview}```",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Risk Factors:*\n{risk_factors_text}",
            },
        },
        {"type": "divider"},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Approve",
                        "emoji": True,
                    },
                    "style": "primary",
                    "action_id": f"governance_approve_{record.chunk_id}",
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Reject",
                        "emoji": True,
                    },
                    "style": "danger",
                    "action_id": f"governance_reject_{record.chunk_id}",
                },
            ],
        },
    ]

    try:
        result = await client.chat_postMessage(
            channel=admin_channel,
            blocks=blocks,
            text=f"Knowledge approval request for chunk {record.chunk_id}",
        )
        ts = result.get("ts")
        channel_id = result.get("channel")

        # Update record with notification tracking info
        if ts:
            from knowledge_base.db.database import async_session_maker
            from sqlalchemy import select

            async with async_session_maker() as session:
                stmt = select(KnowledgeGovernanceRecord).where(
                    KnowledgeGovernanceRecord.chunk_id == record.chunk_id
                )
                db_result = await session.execute(stmt)
                db_record = db_result.scalar_one_or_none()
                if db_record:
                    db_record.slack_notification_ts = ts
                    db_record.slack_notification_channel = channel_id
                    await session.commit()

        logger.info(
            f"Posted HIGH risk approval request for {record.chunk_id} to {admin_channel}"
        )
        return ts

    except Exception as e:
        logger.error(f"Failed to post high-risk notification: {e}", exc_info=True)
        return None


async def notify_admin_medium_risk(
    client: WebClient,
    record: KnowledgeGovernanceRecord,
) -> str | None:
    """Post notification to #knowledge-admins for MEDIUM risk (auto-approved with revert).

    Returns the message timestamp (ts) for tracking, or None on failure.
    """
    admin_channel = _get_admin_channel()

    content_preview = (record.content_preview or "")[:300]
    if len(record.content_preview or "") > 300:
        content_preview += "..."

    revert_deadline_text = "N/A"
    if record.revert_deadline:
        revert_deadline_text = record.revert_deadline.strftime("%Y-%m-%d %H:%M UTC")

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "Knowledge Auto-Approved (Review Window)",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*Risk Score:*\n{record.risk_score:.0f}/100",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Risk Tier:*\n{record.risk_tier.upper()}",
                },
            ],
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*Intake Path:*\n{record.intake_path}",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Submitted By:*\n{record.submitted_by}",
                },
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Content Preview:*\n```{content_preview}```",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Revert Deadline:*\n{revert_deadline_text}",
            },
        },
        {"type": "divider"},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Revert",
                        "emoji": True,
                    },
                    "style": "danger",
                    "action_id": f"governance_revert_{record.chunk_id}",
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Mark Reviewed",
                        "emoji": True,
                    },
                    "style": "primary",
                    "action_id": f"governance_mark_reviewed_{record.chunk_id}",
                },
            ],
        },
    ]

    try:
        result = await client.chat_postMessage(
            channel=admin_channel,
            blocks=blocks,
            text=f"Knowledge auto-approved (review window) for chunk {record.chunk_id}",
        )
        ts = result.get("ts")
        channel_id = result.get("channel")

        # Update record with notification tracking info
        if ts:
            from knowledge_base.db.database import async_session_maker
            from sqlalchemy import select

            async with async_session_maker() as session:
                stmt = select(KnowledgeGovernanceRecord).where(
                    KnowledgeGovernanceRecord.chunk_id == record.chunk_id
                )
                db_result = await session.execute(stmt)
                db_record = db_result.scalar_one_or_none()
                if db_record:
                    db_record.slack_notification_ts = ts
                    db_record.slack_notification_channel = channel_id
                    await session.commit()

        logger.info(
            f"Posted MEDIUM risk notification for {record.chunk_id} to {admin_channel}"
        )
        return ts

    except Exception as e:
        logger.error(f"Failed to post medium-risk notification: {e}", exc_info=True)
        return None


async def handle_governance_approve(ack: Any, body: dict, client: WebClient) -> None:
    """Handle [Approve] button click from admin."""
    await ack()

    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]
    message_ts = body["message"]["ts"]
    action = body["actions"][0]
    action_id = action["action_id"]

    # Authorization: only allow actions from the admin channel
    if await _reject_non_admin(client, channel_id, user_id):
        return

    # Extract chunk_id from action_id: governance_approve_{chunk_id}
    chunk_id = action_id.replace("governance_approve_", "", 1)

    try:
        from knowledge_base.governance.approval_engine import ApprovalEngine

        engine = ApprovalEngine()
        success = await engine.approve(chunk_id, reviewed_by=user_id)

        if success:
            # Update Slack message to remove buttons and show approval
            await client.chat_update(
                channel=channel_id,
                ts=message_ts,
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": (
                                f"*Approved* by an admin at "
                                f"<!date^{int(datetime.utcnow().timestamp())}"
                                f"^{{date_short_pretty}} {{time}}|now>\n"
                                f"Chunk: `{chunk_id}`"
                            ),
                        },
                    },
                ],
                text=f"Approved: {chunk_id}",
            )
            logger.info(f"Governance approve: {chunk_id} by admin")
        else:
            await client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=f"Could not approve `{chunk_id}` -- it may no longer be pending.",
            )

    except Exception as e:
        logger.error(f"Failed to handle governance approve: {e}", exc_info=True)
        await client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=f"Error approving content: {e}",
        )


async def handle_governance_reject(ack: Any, body: dict, client: WebClient) -> None:
    """Handle [Reject] button click -- opens modal for rejection reason."""
    await ack()

    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]

    # Authorization: only allow actions from the admin channel
    if await _reject_non_admin(client, channel_id, user_id):
        return

    action = body["actions"][0]
    action_id = action["action_id"]
    trigger_id = body["trigger_id"]

    # Extract chunk_id from action_id: governance_reject_{chunk_id}
    chunk_id = action_id.replace("governance_reject_", "", 1)

    try:
        await client.views_open(
            trigger_id=trigger_id,
            view={
                "type": "modal",
                "callback_id": "governance_reject_modal",
                "private_metadata": chunk_id,
                "title": {
                    "type": "plain_text",
                    "text": "Reject Content",
                },
                "submit": {
                    "type": "plain_text",
                    "text": "Reject",
                },
                "close": {
                    "type": "plain_text",
                    "text": "Cancel",
                },
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"Rejecting chunk `{chunk_id}`.\nPlease provide a reason:",
                        },
                    },
                    {
                        "type": "input",
                        "block_id": "rejection_reason_block",
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "rejection_reason",
                            "multiline": True,
                            "placeholder": {
                                "type": "plain_text",
                                "text": "Why is this content being rejected?",
                            },
                        },
                        "label": {
                            "type": "plain_text",
                            "text": "Rejection Reason",
                        },
                    },
                ],
            },
        )
    except Exception as e:
        logger.error(f"Failed to open rejection modal: {e}", exc_info=True)


async def handle_governance_reject_submit(
    ack: Any, body: dict, view: dict, client: WebClient
) -> None:
    """Handle rejection modal submission."""
    await ack()

    user_id = body["user"]["id"]
    chunk_id = view["private_metadata"]

    # Extract rejection reason from modal input
    reason = (
        view["state"]["values"]
        .get("rejection_reason_block", {})
        .get("rejection_reason", {})
        .get("value", "")
    )

    try:
        from knowledge_base.governance.approval_engine import ApprovalEngine

        engine = ApprovalEngine()
        success = await engine.reject(chunk_id, reviewed_by=user_id, note=reason)

        admin_channel = _get_admin_channel()

        if success:
            await client.chat_postMessage(
                channel=admin_channel,
                text=(
                    f"*Rejected* `{chunk_id}` by an admin.\n"
                    f"Reason: {reason or 'No reason provided'}"
                ),
            )
            logger.info(f"Governance reject: {chunk_id} by admin")
        else:
            await client.chat_postMessage(
                channel=admin_channel,
                text=f"Could not reject `{chunk_id}` -- it may no longer be pending.",
            )

    except Exception as e:
        logger.error(f"Failed to handle governance reject submit: {e}", exc_info=True)


async def handle_governance_revert(ack: Any, body: dict, client: WebClient) -> None:
    """Handle [Revert] button -- opens confirmation modal before reverting."""
    await ack()

    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]
    action = body["actions"][0]
    action_id = action["action_id"]
    trigger_id = body["trigger_id"]

    # Authorization: only allow actions from the admin channel
    if await _reject_non_admin(client, channel_id, user_id):
        return

    # Extract chunk_id from action_id: governance_revert_{chunk_id}
    chunk_id = action_id.replace("governance_revert_", "", 1)

    try:
        await client.views_open(
            trigger_id=trigger_id,
            view={
                "type": "modal",
                "callback_id": "governance_revert_modal",
                "private_metadata": json.dumps({
                    "chunk_id": chunk_id,
                    "channel_id": channel_id,
                    "message_ts": body["message"]["ts"],
                }),
                "title": {
                    "type": "plain_text",
                    "text": "Revert Content",
                },
                "submit": {
                    "type": "plain_text",
                    "text": "Revert",
                },
                "close": {
                    "type": "plain_text",
                    "text": "Cancel",
                },
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": (
                                f"Are you sure you want to revert chunk `{chunk_id}`?\n"
                                "It will become unsearchable."
                            ),
                        },
                    },
                    {
                        "type": "input",
                        "block_id": "revert_note_block",
                        "optional": True,
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "revert_note",
                            "multiline": True,
                            "placeholder": {
                                "type": "plain_text",
                                "text": "Optional note about why this is being reverted",
                            },
                        },
                        "label": {
                            "type": "plain_text",
                            "text": "Note",
                        },
                    },
                ],
            },
        )
    except Exception as e:
        logger.error(f"Failed to open revert confirmation modal: {e}", exc_info=True)


async def handle_governance_revert_submit(
    ack: Any, body: dict, view: dict, client: WebClient
) -> None:
    """Handle revert confirmation modal submission."""
    await ack()

    user_id = body["user"]["id"]
    meta = json.loads(view["private_metadata"])
    chunk_id = meta["chunk_id"]
    channel_id = meta["channel_id"]
    message_ts = meta["message_ts"]

    # Extract optional note from modal input
    note = (
        view["state"]["values"]
        .get("revert_note_block", {})
        .get("revert_note", {})
        .get("value", "")
    ) or ""

    try:
        from knowledge_base.governance.approval_engine import ApprovalEngine

        engine = ApprovalEngine()
        success = await engine.revert(chunk_id, reviewed_by=user_id)

        if success:
            # Update Slack message to remove buttons and show revert
            await client.chat_update(
                channel=channel_id,
                ts=message_ts,
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": (
                                f"*Reverted* by an admin at "
                                f"<!date^{int(datetime.utcnow().timestamp())}"
                                f"^{{date_short_pretty}} {{time}}|now>\n"
                                f"Chunk: `{chunk_id}`"
                            ),
                        },
                    },
                ],
                text=f"Reverted: {chunk_id}",
            )
            logger.info(f"Governance revert: {chunk_id} by admin")
        else:
            await client.chat_postMessage(
                channel=channel_id,
                text=f"Revert window has expired for `{chunk_id}`. Content cannot be reverted.",
            )

    except Exception as e:
        logger.error(f"Failed to handle governance revert submit: {e}", exc_info=True)


async def handle_governance_mark_reviewed(
    ack: Any, body: dict, client: WebClient
) -> None:
    """Handle [Mark Reviewed] button -- admin confirms medium-risk content is OK.

    No status change needed -- content was already auto-approved.
    Just updates the message to remove buttons and show reviewed status.
    """
    await ack()

    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]
    message_ts = body["message"]["ts"]
    action = body["actions"][0]
    action_id = action["action_id"]

    # Authorization: only allow actions from the admin channel
    if await _reject_non_admin(client, channel_id, user_id):
        return

    chunk_id = action_id.replace("governance_mark_reviewed_", "", 1)

    try:
        await client.chat_update(
            channel=channel_id,
            ts=message_ts,
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"*Reviewed* by an admin at "
                            f"<!date^{int(datetime.utcnow().timestamp())}"
                            f"^{{date_short_pretty}} {{time}}|now>\n"
                            f"Chunk: `{chunk_id}`"
                        ),
                    },
                },
            ],
            text=f"Reviewed: {chunk_id}",
        )
        logger.info(f"Governance mark reviewed: {chunk_id} by admin")

    except Exception as e:
        logger.error(f"Failed to handle governance mark reviewed: {e}", exc_info=True)


async def handle_governance_queue(
    ack: Any, command: dict, client: WebClient
) -> None:
    """Handle /governance-queue command -- show pending items."""
    await ack()

    user_id = command["user_id"]
    channel_id = command["channel_id"]

    try:
        from knowledge_base.governance.approval_engine import ApprovalEngine

        engine = ApprovalEngine()
        pending_items = await engine.get_pending_queue()
        revertable_items = await engine.get_revertable_items()

        if not pending_items and not revertable_items:
            await client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text="No pending items in the governance queue.",
            )
            return

        blocks: list[dict] = []

        # Pending items section
        if pending_items:
            blocks.append({
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"Pending Approval ({len(pending_items)} items)",
                    "emoji": True,
                },
            })

            for item in pending_items:
                preview = (item.content_preview or "")[:150]
                if len(item.content_preview or "") > 150:
                    preview += "..."

                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"*Chunk:* `{item.chunk_id}`\n"
                            f"*Risk:* {item.risk_score:.0f}/100 ({item.risk_tier.upper()})\n"
                            f"*From:* {item.submitted_by} via {item.intake_path}\n"
                            f"*Preview:* {preview}"
                        ),
                    },
                })
                blocks.append({
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Approve", "emoji": True},
                            "style": "primary",
                            "action_id": f"governance_approve_{item.chunk_id}",
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Reject", "emoji": True},
                            "style": "danger",
                            "action_id": f"governance_reject_{item.chunk_id}",
                        },
                    ],
                })
                blocks.append({"type": "divider"})

        # Revertable items section
        if revertable_items:
            blocks.append({
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"Auto-Approved, Revertable ({len(revertable_items)} items)",
                    "emoji": True,
                },
            })

            for item in revertable_items:
                preview = (item.content_preview or "")[:150]
                if len(item.content_preview or "") > 150:
                    preview += "..."

                deadline_text = "N/A"
                if item.revert_deadline:
                    deadline_text = item.revert_deadline.strftime("%Y-%m-%d %H:%M UTC")

                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"*Chunk:* `{item.chunk_id}`\n"
                            f"*Risk:* {item.risk_score:.0f}/100 ({item.risk_tier.upper()})\n"
                            f"*Revert deadline:* {deadline_text}\n"
                            f"*Preview:* {preview}"
                        ),
                    },
                })
                blocks.append({
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Revert", "emoji": True},
                            "style": "danger",
                            "action_id": f"governance_revert_{item.chunk_id}",
                        },
                    ],
                })
                blocks.append({"type": "divider"})

        await client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            blocks=blocks,
            text=f"Governance queue: {len(pending_items)} pending, {len(revertable_items)} revertable",
        )

    except Exception as e:
        logger.error(f"Failed to handle governance queue command: {e}", exc_info=True)
        await client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=f"Error loading governance queue: {e}",
        )


def register_governance_handlers(app) -> None:
    """Register all governance admin handlers with the Slack app."""

    app.action(re.compile(r"governance_approve_.*"))(handle_governance_approve)
    app.action(re.compile(r"governance_reject_.*"))(handle_governance_reject)
    app.action(re.compile(r"governance_revert_.*"))(handle_governance_revert)
    app.action(re.compile(r"governance_mark_reviewed_.*"))(handle_governance_mark_reviewed)
    app.view("governance_reject_modal")(handle_governance_reject_submit)
    app.view("governance_revert_modal")(handle_governance_revert_submit)

    cmd_prefix = settings.SLACK_COMMAND_PREFIX
    app.command(f"/{cmd_prefix}governance-queue")(handle_governance_queue)

    logger.info("Registered governance admin handlers")
