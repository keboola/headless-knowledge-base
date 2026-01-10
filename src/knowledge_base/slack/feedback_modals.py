"""Modal submission handlers for feedback collection (Phase 10.6).

Handles modal submissions for Incorrect, Outdated, and Confusing feedback types.
Captures detailed information and notifies content owners.
"""

import json
import logging
from typing import Any

from slack_sdk import WebClient

from knowledge_base.db.database import init_db
from knowledge_base.lifecycle.feedback import submit_feedback
from knowledge_base.slack.owner_notification import (
    confirm_feedback_to_reporter,
    notify_content_owner,
)

logger = logging.getLogger(__name__)


async def handle_incorrect_modal_submit(
    ack: Any, body: dict, client: WebClient, view: dict
) -> None:
    """Handle submission of 'Incorrect' feedback modal.

    Extracts:
    - What was incorrect (required)
    - Correct information (optional)
    - Evidence type (how they know)

    Then submits feedback and notifies content owner.
    """
    await ack()
    await init_db()

    try:
        # Extract metadata
        metadata = json.loads(view.get("private_metadata", "{}"))
        message_ts = metadata.get("message_ts")
        chunk_ids = metadata.get("chunk_ids", [])
        channel_id = metadata.get("channel_id")
        reporter_id = metadata.get("reporter_id")

        # Extract form values
        values = view["state"]["values"]

        what_incorrect = (
            values.get("incorrect_block", {})
            .get("incorrect_input", {})
            .get("value", "")
        )
        correct_info = (
            values.get("correction_block", {})
            .get("correction_input", {})
            .get("value")
        )
        evidence_option = (
            values.get("evidence_block", {})
            .get("evidence_select", {})
            .get("selected_option")
        )
        evidence = evidence_option.get("value") if evidence_option else None

        # Build comment with context
        comment = what_incorrect
        if evidence:
            comment += f"\n\n[Evidence: {evidence}]"

        # Get user info
        try:
            user_info = client.users_info(user=reporter_id)
            username = user_info["user"]["name"]
        except Exception:
            username = reporter_id

        # Submit feedback for each chunk
        for chunk_id in chunk_ids:
            await submit_feedback(
                chunk_id=chunk_id,
                slack_user_id=reporter_id,
                slack_username=username,
                feedback_type="incorrect",
                slack_channel_id=channel_id,
                comment=comment,
                suggested_correction=correct_info,
                conversation_thread_ts=message_ts,
            )

        # Notify content owner
        owner_notified = await notify_content_owner(
            client=client,
            chunk_ids=chunk_ids,
            feedback_type="incorrect",
            issue_description=what_incorrect,
            suggested_correction=correct_info,
            reporter_id=reporter_id,
            channel_id=channel_id,
            message_ts=message_ts,
        )

        # Confirm to reporter
        await confirm_feedback_to_reporter(
            client=client,
            channel_id=channel_id,
            reporter_id=reporter_id,
            feedback_type="incorrect",
            owner_notified=owner_notified,
        )

        logger.info(
            f"Processed incorrect feedback from {reporter_id} "
            f"for {len(chunk_ids)} chunks (owner_notified={owner_notified})"
        )

    except Exception as e:
        logger.error(f"Failed to process incorrect feedback modal: {e}", exc_info=True)


async def handle_outdated_modal_submit(
    ack: Any, body: dict, client: WebClient, view: dict
) -> None:
    """Handle submission of 'Outdated' feedback modal.

    Extracts:
    - What is outdated (required)
    - Current/correct information (optional)
    - When it changed (optional)

    Then submits feedback and notifies content owner.
    """
    await ack()
    await init_db()

    try:
        # Extract metadata
        metadata = json.loads(view.get("private_metadata", "{}"))
        message_ts = metadata.get("message_ts")
        chunk_ids = metadata.get("chunk_ids", [])
        channel_id = metadata.get("channel_id")
        reporter_id = metadata.get("reporter_id")

        # Extract form values
        values = view["state"]["values"]

        what_outdated = (
            values.get("outdated_block", {})
            .get("outdated_input", {})
            .get("value", "")
        )
        current_info = (
            values.get("current_block", {})
            .get("current_input", {})
            .get("value")
        )
        when_changed = (
            values.get("when_block", {})
            .get("when_input", {})
            .get("value")
        )

        # Build comment with context
        comment = what_outdated
        if when_changed:
            comment += f"\n\n[Changed: {when_changed}]"

        # Get user info
        try:
            user_info = client.users_info(user=reporter_id)
            username = user_info["user"]["name"]
        except Exception:
            username = reporter_id

        # Submit feedback for each chunk
        for chunk_id in chunk_ids:
            await submit_feedback(
                chunk_id=chunk_id,
                slack_user_id=reporter_id,
                slack_username=username,
                feedback_type="outdated",
                slack_channel_id=channel_id,
                comment=comment,
                suggested_correction=current_info,
                conversation_thread_ts=message_ts,
            )

        # Notify content owner
        owner_notified = await notify_content_owner(
            client=client,
            chunk_ids=chunk_ids,
            feedback_type="outdated",
            issue_description=what_outdated,
            suggested_correction=current_info,
            reporter_id=reporter_id,
            channel_id=channel_id,
            message_ts=message_ts,
        )

        # Confirm to reporter
        await confirm_feedback_to_reporter(
            client=client,
            channel_id=channel_id,
            reporter_id=reporter_id,
            feedback_type="outdated",
            owner_notified=owner_notified,
        )

        logger.info(
            f"Processed outdated feedback from {reporter_id} "
            f"for {len(chunk_ids)} chunks (owner_notified={owner_notified})"
        )

    except Exception as e:
        logger.error(f"Failed to process outdated feedback modal: {e}", exc_info=True)


async def handle_confusing_modal_submit(
    ack: Any, body: dict, client: WebClient, view: dict
) -> None:
    """Handle submission of 'Confusing' feedback modal.

    Extracts:
    - Confusion type (why it was confusing)
    - Clarification needed (optional)

    Then submits feedback and notifies content owner.
    """
    await ack()
    await init_db()

    try:
        # Extract metadata
        metadata = json.loads(view.get("private_metadata", "{}"))
        message_ts = metadata.get("message_ts")
        chunk_ids = metadata.get("chunk_ids", [])
        channel_id = metadata.get("channel_id")
        reporter_id = metadata.get("reporter_id")

        # Extract form values
        values = view["state"]["values"]

        confusion_option = (
            values.get("confusion_block", {})
            .get("confusion_select", {})
            .get("selected_option")
        )
        confusion_type = confusion_option.get("value") if confusion_option else "unclear"
        confusion_text = confusion_option.get("text", {}).get("text", "") if confusion_option else ""

        clarification = (
            values.get("clarification_block", {})
            .get("clarification_input", {})
            .get("value")
        )

        # Build comment with context
        comment = f"Confusion type: {confusion_text or confusion_type}"
        if clarification:
            comment += f"\n\nNeeds clarification: {clarification}"

        # Get user info
        try:
            user_info = client.users_info(user=reporter_id)
            username = user_info["user"]["name"]
        except Exception:
            username = reporter_id

        # Submit feedback for each chunk
        for chunk_id in chunk_ids:
            await submit_feedback(
                chunk_id=chunk_id,
                slack_user_id=reporter_id,
                slack_username=username,
                feedback_type="confusing",
                slack_channel_id=channel_id,
                comment=comment,
                suggested_correction=clarification,  # Use clarification as suggested improvement
                conversation_thread_ts=message_ts,
            )

        # Notify content owner
        owner_notified = await notify_content_owner(
            client=client,
            chunk_ids=chunk_ids,
            feedback_type="confusing",
            issue_description=comment,
            suggested_correction=clarification,
            reporter_id=reporter_id,
            channel_id=channel_id,
            message_ts=message_ts,
        )

        # Confirm to reporter
        await confirm_feedback_to_reporter(
            client=client,
            channel_id=channel_id,
            reporter_id=reporter_id,
            feedback_type="confusing",
            owner_notified=owner_notified,
        )

        logger.info(
            f"Processed confusing feedback from {reporter_id} "
            f"for {len(chunk_ids)} chunks (owner_notified={owner_notified})"
        )

    except Exception as e:
        logger.error(f"Failed to process confusing feedback modal: {e}", exc_info=True)


def register_feedback_modal_handlers(app) -> None:
    """Register feedback modal view handlers with the Slack app.

    Args:
        app: Slack Bolt app instance
    """
    app.view("feedback_incorrect_modal")(handle_incorrect_modal_submit)
    app.view("feedback_outdated_modal")(handle_outdated_modal_submit)
    app.view("feedback_confusing_modal")(handle_confusing_modal_submit)

    logger.info("Registered feedback modal handlers")
