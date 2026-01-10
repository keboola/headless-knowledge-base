"""Modal builders for Slack document creation."""

from knowledge_base.documents.models import (
    DocumentArea,
    DocumentType,
    Classification,
)


def build_create_doc_modal() -> dict:
    """Build the create document modal."""
    return {
        "type": "modal",
        "callback_id": "create_doc_modal",
        "title": {"type": "plain_text", "text": "Create Document"},
        "submit": {"type": "plain_text", "text": "Create Draft"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            _title_input_block(),
            _area_select_block(),
            _type_select_block(),
            _classification_select_block(),
            _creation_mode_block(),
            _description_input_block(),
        ],
    }


def build_thread_to_doc_modal(channel_id: str, thread_ts: str) -> dict:
    """Build the thread-to-doc modal.

    Args:
        channel_id: Slack channel ID where thread exists
        thread_ts: Thread timestamp
    """
    import json

    return {
        "type": "modal",
        "callback_id": "thread_to_doc_modal",
        "private_metadata": json.dumps({
            "channel_id": channel_id,
            "thread_ts": thread_ts,
        }),
        "title": {"type": "plain_text", "text": "Save Thread as Doc"},
        "submit": {"type": "plain_text", "text": "Create Document"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "Create a document from this thread conversation. "
                    "AI will summarize the discussion into a structured document.",
                },
            },
            {"type": "divider"},
            _area_select_block(),
            _type_select_block(),
            _classification_select_block(),
        ],
    }


def build_doc_preview_modal(
    doc_id: str,
    title: str,
    content: str,
    area: str,
    doc_type: str,
    status: str,
) -> dict:
    """Build a modal showing document preview.

    Args:
        doc_id: Document ID
        title: Document title
        content: Document content
        area: Document area
        doc_type: Document type
        status: Document status
    """
    # Truncate content for modal display
    preview_content = content[:2500] + "..." if len(content) > 2500 else content

    return {
        "type": "modal",
        "callback_id": "doc_preview_modal",
        "title": {"type": "plain_text", "text": "Document Preview"},
        "close": {"type": "plain_text", "text": "Close"},
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": title},
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Area:* {area} | *Type:* {doc_type} | *Status:* {status}",
                    }
                ],
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": preview_content},
            },
        ],
    }


def build_rejection_reason_modal(doc_id: str, title: str) -> dict:
    """Build modal for rejection reason.

    Args:
        doc_id: Document ID being rejected
        title: Document title
    """
    import json

    return {
        "type": "modal",
        "callback_id": "rejection_reason_modal",
        "private_metadata": json.dumps({"doc_id": doc_id}),
        "title": {"type": "plain_text", "text": "Reject Document"},
        "submit": {"type": "plain_text", "text": "Reject"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"You are rejecting: *{title}*\n\n"
                    "Please provide a reason for rejection so the author can improve the document.",
                },
            },
            {
                "type": "input",
                "block_id": "rejection_reason_block",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "rejection_reason_input",
                    "multiline": True,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "Explain what needs to be improved...",
                    },
                },
                "label": {"type": "plain_text", "text": "Rejection Reason"},
            },
        ],
    }


def build_doc_created_message(
    doc_id: str,
    title: str,
    status: str,
    doc_type: str,
    area: str,
    requires_approval: bool,
) -> list[dict]:
    """Build message blocks for document creation notification.

    Args:
        doc_id: Document ID
        title: Document title
        status: Document status
        doc_type: Document type
        area: Document area
        requires_approval: Whether document requires approval
    """
    status_emoji = {
        "draft": "📝",
        "in_review": "🔄",
        "approved": "✅",
        "published": "📗",
        "rejected": "❌",
        "archived": "📦",
    }.get(status, "📄")

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{status_emoji} *Document Created*\n\n"
                f"*{title}*\n"
                f"Area: {area} | Type: {doc_type}\n"
                f"Status: {status.upper()}",
            },
        },
    ]

    # Add action buttons based on status
    actions = []

    if status == "draft" and requires_approval:
        actions.append({
            "type": "button",
            "text": {"type": "plain_text", "text": "Submit for Approval"},
            "style": "primary",
            "action_id": f"submit_doc_{doc_id}",
        })

    actions.append({
        "type": "button",
        "text": {"type": "plain_text", "text": "Edit"},
        "action_id": f"edit_doc_{doc_id}",
    })

    actions.append({
        "type": "button",
        "text": {"type": "plain_text", "text": "View Full"},
        "action_id": f"view_doc_{doc_id}",
    })

    if actions:
        blocks.append({"type": "actions", "elements": actions})

    return blocks


# =============================================================================
# Feedback Modals (Phase 10.6)
# =============================================================================


def build_incorrect_feedback_modal(
    message_ts: str,
    chunk_ids: list[str],
    channel_id: str,
    reporter_id: str,
) -> dict:
    """Build modal for 'Incorrect' feedback - captures what's wrong and correction.

    Args:
        message_ts: Original message timestamp
        chunk_ids: List of chunk IDs associated with the response
        channel_id: Channel where feedback originated
        reporter_id: User reporting the issue
    """
    import json

    return {
        "type": "modal",
        "callback_id": "feedback_incorrect_modal",
        "private_metadata": json.dumps({
            "message_ts": message_ts,
            "chunk_ids": chunk_ids,
            "channel_id": channel_id,
            "reporter_id": reporter_id,
        }),
        "title": {"type": "plain_text", "text": "Report Incorrect Info"},
        "submit": {"type": "plain_text", "text": "Submit Report"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": ":x: *Report Incorrect Information*\n\n"
                    "Help us improve by telling us what's wrong and what the correct information should be.",
                },
            },
            {"type": "divider"},
            {
                "type": "input",
                "block_id": "incorrect_block",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "incorrect_input",
                    "multiline": True,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "What specifically is incorrect? (e.g., 'The VPN address is wrong')",
                    },
                },
                "label": {"type": "plain_text", "text": "What is incorrect?"},
            },
            {
                "type": "input",
                "block_id": "correction_block",
                "optional": True,
                "element": {
                    "type": "plain_text_input",
                    "action_id": "correction_input",
                    "multiline": True,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "What is the correct information? (e.g., 'The correct VPN is vpn.company.com')",
                    },
                },
                "label": {"type": "plain_text", "text": "What is the correct information?"},
            },
            {
                "type": "input",
                "block_id": "evidence_block",
                "optional": True,
                "element": {
                    "type": "static_select",
                    "action_id": "evidence_select",
                    "options": [
                        {"text": {"type": "plain_text", "text": "I verified it myself"}, "value": "verified"},
                        {"text": {"type": "plain_text", "text": "IT/HR told me"}, "value": "told"},
                        {"text": {"type": "plain_text", "text": "It's in official documentation"}, "value": "documented"},
                        {"text": {"type": "plain_text", "text": "Other"}, "value": "other"},
                    ],
                    "placeholder": {"type": "plain_text", "text": "How do you know?"},
                },
                "label": {"type": "plain_text", "text": "How do you know this?"},
            },
        ],
    }


def build_outdated_feedback_modal(
    message_ts: str,
    chunk_ids: list[str],
    channel_id: str,
    reporter_id: str,
) -> dict:
    """Build modal for 'Outdated' feedback - captures what changed.

    Args:
        message_ts: Original message timestamp
        chunk_ids: List of chunk IDs associated with the response
        channel_id: Channel where feedback originated
        reporter_id: User reporting the issue
    """
    import json

    return {
        "type": "modal",
        "callback_id": "feedback_outdated_modal",
        "private_metadata": json.dumps({
            "message_ts": message_ts,
            "chunk_ids": chunk_ids,
            "channel_id": channel_id,
            "reporter_id": reporter_id,
        }),
        "title": {"type": "plain_text", "text": "Report Outdated Info"},
        "submit": {"type": "plain_text", "text": "Submit Report"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": ":hourglass: *Report Outdated Information*\n\n"
                    "Help us keep content up-to-date by telling us what has changed.",
                },
            },
            {"type": "divider"},
            {
                "type": "input",
                "block_id": "outdated_block",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "outdated_input",
                    "multiline": True,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "What is outdated? (e.g., 'This policy was updated last month')",
                    },
                },
                "label": {"type": "plain_text", "text": "What is outdated?"},
            },
            {
                "type": "input",
                "block_id": "current_info_block",
                "optional": True,
                "element": {
                    "type": "plain_text_input",
                    "action_id": "current_info_input",
                    "multiline": True,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "What is the current/updated information?",
                    },
                },
                "label": {"type": "plain_text", "text": "What is the current information?"},
            },
            {
                "type": "input",
                "block_id": "when_changed_block",
                "optional": True,
                "element": {
                    "type": "plain_text_input",
                    "action_id": "when_changed_input",
                    "placeholder": {
                        "type": "plain_text",
                        "text": "e.g., 'Last week', 'January 2025'",
                    },
                },
                "label": {"type": "plain_text", "text": "When did this change?"},
            },
        ],
    }


def build_confusing_feedback_modal(
    message_ts: str,
    chunk_ids: list[str],
    channel_id: str,
    reporter_id: str,
) -> dict:
    """Build modal for 'Confusing' feedback - captures what was unclear.

    Args:
        message_ts: Original message timestamp
        chunk_ids: List of chunk IDs associated with the response
        channel_id: Channel where feedback originated
        reporter_id: User reporting the issue
    """
    import json

    return {
        "type": "modal",
        "callback_id": "feedback_confusing_modal",
        "private_metadata": json.dumps({
            "message_ts": message_ts,
            "chunk_ids": chunk_ids,
            "channel_id": channel_id,
            "reporter_id": reporter_id,
        }),
        "title": {"type": "plain_text", "text": "Report Confusing Info"},
        "submit": {"type": "plain_text", "text": "Submit Report"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": ":thinking_face: *Report Confusing Information*\n\n"
                    "Help us clarify content by telling us what was unclear.",
                },
            },
            {"type": "divider"},
            {
                "type": "input",
                "block_id": "confusion_type_block",
                "element": {
                    "type": "static_select",
                    "action_id": "confusion_type_select",
                    "options": [
                        {"text": {"type": "plain_text", "text": "Answer didn't match my question"}, "value": "mismatch"},
                        {"text": {"type": "plain_text", "text": "Too technical / jargon"}, "value": "technical"},
                        {"text": {"type": "plain_text", "text": "Missing steps or context"}, "value": "incomplete"},
                        {"text": {"type": "plain_text", "text": "Contradictory information"}, "value": "contradictory"},
                        {"text": {"type": "plain_text", "text": "Other"}, "value": "other"},
                    ],
                    "placeholder": {"type": "plain_text", "text": "Select what was confusing"},
                },
                "label": {"type": "plain_text", "text": "What was confusing?"},
            },
            {
                "type": "input",
                "block_id": "clarification_block",
                "optional": True,
                "element": {
                    "type": "plain_text_input",
                    "action_id": "clarification_input",
                    "multiline": True,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "What would have helped? What were you expecting?",
                    },
                },
                "label": {"type": "plain_text", "text": "How could this be clearer?"},
            },
        ],
    }


# =============================================================================
# Block Builders
# =============================================================================


def _title_input_block() -> dict:
    """Build title input block."""
    return {
        "type": "input",
        "block_id": "title_block",
        "element": {
            "type": "plain_text_input",
            "action_id": "title_input",
            "placeholder": {"type": "plain_text", "text": "Enter document title"},
        },
        "label": {"type": "plain_text", "text": "Title"},
    }


def _area_select_block() -> dict:
    """Build area select block."""
    options = [
        {
            "text": {"type": "plain_text", "text": area.value.replace("_", " ").title()},
            "value": area.value,
        }
        for area in DocumentArea
    ]
    return {
        "type": "input",
        "block_id": "area_block",
        "element": {
            "type": "static_select",
            "action_id": "area_select",
            "options": options,
            "initial_option": options[0],
            "placeholder": {"type": "plain_text", "text": "Select area"},
        },
        "label": {"type": "plain_text", "text": "Document Area"},
    }


def _type_select_block() -> dict:
    """Build document type select block."""
    options = [
        {
            "text": {"type": "plain_text", "text": doc_type.value.title()},
            "value": doc_type.value,
        }
        for doc_type in DocumentType
    ]
    return {
        "type": "input",
        "block_id": "type_block",
        "element": {
            "type": "static_select",
            "action_id": "type_select",
            "options": options,
            "initial_option": options[0],
            "placeholder": {"type": "plain_text", "text": "Select type"},
        },
        "label": {"type": "plain_text", "text": "Document Type"},
        "hint": {
            "type": "plain_text",
            "text": "Policy/Procedure require approval. Guideline/Information are auto-published.",
        },
    }


def _classification_select_block() -> dict:
    """Build classification select block."""
    options = [
        {
            "text": {"type": "plain_text", "text": c.value.title()},
            "value": c.value,
        }
        for c in Classification
    ]
    return {
        "type": "input",
        "block_id": "classification_block",
        "element": {
            "type": "static_select",
            "action_id": "classification_select",
            "options": options,
            "initial_option": options[1],  # Default to "internal"
            "placeholder": {"type": "plain_text", "text": "Select classification"},
        },
        "label": {"type": "plain_text", "text": "Classification"},
        "optional": True,
    }


def _creation_mode_block() -> dict:
    """Build creation mode selection block."""
    return {
        "type": "input",
        "block_id": "mode_block",
        "element": {
            "type": "radio_buttons",
            "action_id": "mode_select",
            "options": [
                {
                    "text": {"type": "plain_text", "text": "AI-assisted draft"},
                    "value": "ai",
                },
                {
                    "text": {"type": "plain_text", "text": "Manual content"},
                    "value": "manual",
                },
            ],
            "initial_option": {
                "text": {"type": "plain_text", "text": "AI-assisted draft"},
                "value": "ai",
            },
        },
        "label": {"type": "plain_text", "text": "Creation Mode"},
    }


def _description_input_block() -> dict:
    """Build description/content input block."""
    return {
        "type": "input",
        "block_id": "description_block",
        "element": {
            "type": "plain_text_input",
            "action_id": "description_input",
            "multiline": True,
            "placeholder": {
                "type": "plain_text",
                "text": "For AI mode: Describe what this document should cover.\n"
                "For Manual mode: Write the document content directly.",
            },
        },
        "label": {"type": "plain_text", "text": "Description / Content"},
    }
