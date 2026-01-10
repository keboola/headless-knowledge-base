"""Document creation handlers for Slack."""

import asyncio
import json
import logging
import re
from typing import Any

from slack_bolt import App
from slack_sdk import WebClient

from knowledge_base.db.database import init_db
from knowledge_base.documents.creator import DocumentCreator
from knowledge_base.documents.approval import ApprovalConfig
from knowledge_base.documents.models import (
    ApprovalDecision,
    DocumentArea,
    DocumentType,
    Classification,
    requires_approval,
)
from knowledge_base.slack.modals import (
    build_create_doc_modal,
    build_thread_to_doc_modal,
    build_doc_preview_modal,
    build_rejection_reason_modal,
    build_doc_created_message,
)

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Safely run an async coroutine from a sync context."""
    try:
        return asyncio.run(coro)
    except RuntimeError as e:
        if "cannot be called from a running event loop" in str(e):
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as executor:
                return executor.submit(asyncio.run, coro).result()
        raise


def _get_document_creator(slack_client=None) -> DocumentCreator:
    """Get a DocumentCreator instance with database session."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from knowledge_base.config import settings
    from knowledge_base.db.models import Base

    # Create sync session
    sync_db_url = settings.DATABASE_URL.replace("+aiosqlite", "")
    engine = create_engine(sync_db_url)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # Try to get LLM
    llm = None
    try:
        from knowledge_base.rag.factory import get_llm as get_llm_async

        llm = _run_async(get_llm_async())
    except Exception as e:
        logger.warning(f"LLM not available: {e}")

    config = ApprovalConfig(require_all_approvers=False)
    return DocumentCreator(
        session=session,
        llm=llm,
        approval_config=config,
        slack_client=slack_client,
    )


# =========================================================================
# Slash Command Handlers
# =========================================================================


def handle_create_doc_command(ack: Any, body: dict, client: WebClient) -> None:
    """Handle /create-doc slash command."""
    ack()

    try:
        client.views_open(
            trigger_id=body["trigger_id"],
            view=build_create_doc_modal(),
        )
    except Exception as e:
        logger.error(f"Failed to open create-doc modal: {e}")


# =========================================================================
# Shortcut Handlers
# =========================================================================


def handle_save_as_doc(ack: Any, shortcut: dict, client: WebClient) -> None:
    """Handle 'Save as Doc' message shortcut."""
    ack()

    try:
        channel_id = shortcut["channel"]["id"]
        message = shortcut["message"]
        message_ts = message.get("ts", "")
        thread_ts = message.get("thread_ts", message_ts)

        client.views_open(
            trigger_id=shortcut["trigger_id"],
            view=build_thread_to_doc_modal(channel_id, thread_ts),
        )
    except Exception as e:
        logger.error(f"Failed to open thread-to-doc modal: {e}")


# =========================================================================
# Modal Submission Handlers
# =========================================================================


def handle_create_doc_submit(
    ack: Any, body: dict, client: WebClient, view: dict
) -> None:
    """Handle create document modal submission."""
    ack()

    user_id = body["user"]["id"]
    values = view["state"]["values"]

    try:
        # Extract form values
        title = values["title_block"]["title_input"]["value"]
        area = values["area_block"]["area_select"]["selected_option"]["value"]
        doc_type = values["type_block"]["type_select"]["selected_option"]["value"]
        classification = values["classification_block"]["classification_select"][
            "selected_option"
        ]["value"]
        mode = values["mode_block"]["mode_select"]["selected_option"]["value"]
        description = values["description_block"]["description_input"]["value"]

        _run_async(init_db())
        creator = _get_document_creator(slack_client=client)

        if mode == "ai":
            # AI-assisted creation
            if not creator.drafter:
                client.chat_postMessage(
                    channel=user_id,
                    text="LLM not configured. Please try again with manual mode.",
                )
                return

            doc, draft_result = _run_async(
                creator.create_from_description(
                    title=title,
                    description=description,
                    area=area,
                    doc_type=doc_type,
                    created_by=user_id,
                    classification=classification,
                )
            )

            # Send confirmation with draft info
            blocks = build_doc_created_message(
                doc_id=doc.doc_id,
                title=doc.title,
                status=doc.status,
                doc_type=doc.doc_type,
                area=doc.area,
                requires_approval=requires_approval(doc_type),
            )

            # Add confidence info
            blocks.insert(
                1,
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"_AI Confidence: {draft_result.confidence * 100:.0f}%_",
                        }
                    ],
                },
            )

            client.chat_postMessage(
                channel=user_id, blocks=blocks, text=f"Document '{title}' created!"
            )
        else:
            # Manual creation
            doc = _run_async(
                creator.create_manual(
                    title=title,
                    content=description,
                    area=area,
                    doc_type=doc_type,
                    created_by=user_id,
                    classification=classification,
                )
            )

            blocks = build_doc_created_message(
                doc_id=doc.doc_id,
                title=doc.title,
                status=doc.status,
                doc_type=doc.doc_type,
                area=doc.area,
                requires_approval=requires_approval(doc_type),
            )

            client.chat_postMessage(
                channel=user_id, blocks=blocks, text=f"Document '{title}' created!"
            )

    except Exception as e:
        logger.error(f"Failed to create document: {e}")
        client.chat_postMessage(
            channel=user_id,
            text=f"Failed to create document: {e}",
        )


def handle_thread_to_doc_submit(
    ack: Any, body: dict, client: WebClient, view: dict
) -> None:
    """Handle thread-to-doc modal submission."""
    ack()

    user_id = body["user"]["id"]
    values = view["state"]["values"]
    metadata = json.loads(view.get("private_metadata", "{}"))

    try:
        channel_id = metadata.get("channel_id")
        thread_ts = metadata.get("thread_ts")

        if not channel_id or not thread_ts:
            client.chat_postMessage(
                channel=user_id,
                text="Error: Could not find thread information.",
            )
            return

        # Extract form values
        area = values["area_block"]["area_select"]["selected_option"]["value"]
        doc_type = values["type_block"]["type_select"]["selected_option"]["value"]
        classification = values["classification_block"]["classification_select"][
            "selected_option"
        ]["value"]

        # Fetch thread messages
        result = client.conversations_replies(channel=channel_id, ts=thread_ts)
        messages = result.get("messages", [])

        if not messages:
            client.chat_postMessage(
                channel=user_id,
                text="Error: Could not fetch thread messages.",
            )
            return

        # Format messages for the creator
        thread_messages = [
            {"user": m.get("user", "unknown"), "text": m.get("text", "")}
            for m in messages
        ]

        _run_async(init_db())
        creator = _get_document_creator(slack_client=client)

        if not creator.drafter:
            client.chat_postMessage(
                channel=user_id,
                text="LLM not configured. Thread summarization requires AI.",
            )
            return

        doc, draft_result = _run_async(
            creator.create_from_thread(
                thread_messages=thread_messages,
                channel_id=channel_id,
                thread_ts=thread_ts,
                area=area,
                created_by=user_id,
                doc_type=doc_type,
                classification=classification,
            )
        )

        blocks = build_doc_created_message(
            doc_id=doc.doc_id,
            title=doc.title,
            status=doc.status,
            doc_type=doc.doc_type,
            area=doc.area,
            requires_approval=requires_approval(doc_type),
        )

        client.chat_postMessage(
            channel=user_id,
            blocks=blocks,
            text=f"Document '{doc.title}' created from thread!",
        )

    except Exception as e:
        logger.error(f"Failed to create document from thread: {e}")
        client.chat_postMessage(
            channel=user_id,
            text=f"Failed to create document from thread: {e}",
        )


def handle_rejection_submit(
    ack: Any, body: dict, client: WebClient, view: dict
) -> None:
    """Handle rejection reason modal submission."""
    ack()

    user_id = body["user"]["id"]
    values = view["state"]["values"]
    metadata = json.loads(view.get("private_metadata", "{}"))

    try:
        doc_id = metadata.get("doc_id")
        rejection_reason = values["rejection_reason_block"]["rejection_reason_input"][
            "value"
        ]

        if not doc_id:
            return

        _run_async(init_db())
        creator = _get_document_creator(slack_client=client)

        decision = ApprovalDecision(
            doc_id=doc_id,
            approved=False,
            approver_id=user_id,
            rejection_reason=rejection_reason,
        )

        _run_async(creator.approval.process_decision(decision))

        client.chat_postMessage(
            channel=user_id,
            text="Document rejected. The author has been notified.",
        )

    except Exception as e:
        logger.error(f"Failed to process rejection: {e}")
        client.chat_postMessage(
            channel=user_id,
            text=f"Failed to process rejection: {e}",
        )


# =========================================================================
# Action Handlers: Approval Workflow
# =========================================================================


def handle_approve_doc(ack: Any, body: dict, client: WebClient) -> None:
    """Handle document approval button click."""
    ack()

    user_id = body["user"]["id"]
    action_id = body["actions"][0]["action_id"]
    doc_id = action_id.replace("approve_doc_", "")

    try:
        _run_async(init_db())
        creator = _get_document_creator(slack_client=client)

        decision = ApprovalDecision(
            doc_id=doc_id,
            approved=True,
            approver_id=user_id,
        )

        status = _run_async(creator.approval.process_decision(decision))

        # Update the message to show approval
        client.chat_postEphemeral(
            channel=body["channel"]["id"],
            user=user_id,
            text=f"Document approved! Status: {status.status}",
        )

    except Exception as e:
        logger.error(f"Failed to approve document: {e}")
        client.chat_postEphemeral(
            channel=body["channel"]["id"],
            user=user_id,
            text=f"Failed to approve: {e}",
        )


def handle_reject_doc(ack: Any, body: dict, client: WebClient) -> None:
    """Handle document rejection button click - opens reason modal."""
    ack()

    action_id = body["actions"][0]["action_id"]
    doc_id = action_id.replace("reject_doc_", "")

    try:
        # Get document title
        _run_async(init_db())
        creator = _get_document_creator()
        doc = creator.get_document(doc_id)
        title = doc.title if doc else "Unknown Document"

        client.views_open(
            trigger_id=body["trigger_id"],
            view=build_rejection_reason_modal(doc_id, title),
        )
    except Exception as e:
        logger.error(f"Failed to open rejection modal: {e}")


def handle_submit_for_approval(ack: Any, body: dict, client: WebClient) -> None:
    """Handle submit for approval button click."""
    ack()

    user_id = body["user"]["id"]
    action_id = body["actions"][0]["action_id"]
    doc_id = action_id.replace("submit_doc_", "")

    try:
        _run_async(init_db())
        creator = _get_document_creator(slack_client=client)

        doc = _run_async(creator.submit_for_approval(doc_id, user_id))

        client.chat_postEphemeral(
            channel=body["channel"]["id"],
            user=user_id,
            text=f"Document submitted for approval! Status: {doc.status}",
        )

    except Exception as e:
        logger.error(f"Failed to submit for approval: {e}")
        client.chat_postEphemeral(
            channel=body["channel"]["id"],
            user=user_id,
            text=f"Failed to submit: {e}",
        )


def handle_view_doc(ack: Any, body: dict, client: WebClient) -> None:
    """Handle view document button click - opens preview modal."""
    ack()

    action_id = body["actions"][0]["action_id"]
    doc_id = action_id.replace("view_doc_", "")

    try:
        _run_async(init_db())
        creator = _get_document_creator()
        doc = creator.get_document(doc_id)

        if not doc:
            return

        client.views_open(
            trigger_id=body["trigger_id"],
            view=build_doc_preview_modal(
                doc_id=doc.doc_id,
                title=doc.title,
                content=doc.content,
                area=doc.area,
                doc_type=doc.doc_type,
                status=doc.status,
            ),
        )

    except Exception as e:
        logger.error(f"Failed to show document preview: {e}")


def handle_edit_doc(ack: Any, body: dict, client: WebClient) -> None:
    """Handle edit document button click."""
    ack()

    user_id = body["user"]["id"]
    action_id = body["actions"][0]["action_id"]
    doc_id = action_id.replace("edit_doc_", "")

    # For now, direct users to the web UI for editing
    client.chat_postEphemeral(
        channel=body["channel"]["id"],
        user=user_id,
        text=f"To edit this document, please use the web UI:\n"
        f"`streamlit run src/knowledge_base/web/streamlit_app.py`\n\n"
        f"Document ID: `{doc_id}`",
    )


def register_doc_handlers(app: App) -> None:
    """Register all document creation handlers with the Slack app.

    Args:
        app: Slack Bolt App instance
    """
    # Slash Commands
    app.command("/create-doc")(handle_create_doc_command)

    # Shortcuts
    app.shortcut("save_as_doc")(handle_save_as_doc)

    # Modal Submissions
    app.view("create_doc_modal")(handle_create_doc_submit)
    app.view("thread_to_doc_modal")(handle_thread_to_doc_submit)
    app.view("rejection_reason_modal")(handle_rejection_submit)

    # Action Handlers
    app.action(re.compile(r"approve_doc_.*"))(handle_approve_doc)
    app.action(re.compile(r"reject_doc_.*"))(handle_reject_doc)
    app.action(re.compile(r"submit_doc_.*"))(handle_submit_for_approval)
    app.action(re.compile(r"view_doc_.*"))(handle_view_doc)
    app.action(re.compile(r"edit_doc_.*"))(handle_edit_doc)
