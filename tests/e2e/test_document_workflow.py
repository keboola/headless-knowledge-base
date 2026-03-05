"""E2E tests for Document Creation and Approval workflow."""

import pytest
import uuid
import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy import select

from knowledge_base.db.models import Document, AreaApprover
from knowledge_base.documents.models import ApprovalDecision
from knowledge_base.slack.doc_creation import (
    handle_create_doc_submit,
    handle_approve_doc,
    handle_submit_for_approval,
)

logger = logging.getLogger(__name__)

# Mark all tests in this module as e2e
pytestmark = pytest.mark.e2e

# Patch targets for doc_creation internals
_PATCH_INIT_DB = "knowledge_base.slack.doc_creation.init_db"
_PATCH_GET_CREATOR = "knowledge_base.slack.doc_creation._get_document_creator"


def _make_mock_doc(
    doc_id=None,
    title="Test Doc",
    status="published",
    doc_type="guideline",
    area="engineering",
    content="Test content",
    created_by="U12345",
    approved_by=None,
    approved_at=None,
):
    """Create a mock Document object with the given attributes."""
    doc = MagicMock()
    doc.doc_id = doc_id or str(uuid.uuid4())
    doc.title = title
    doc.status = status
    doc.doc_type = doc_type
    doc.area = area
    doc.content = content
    doc.created_by = created_by
    doc.approved_by = approved_by
    doc.approved_at = approved_at
    return doc


def _make_mock_creator(doc=None):
    """Create a mock DocumentCreator with async methods."""
    creator = MagicMock()
    creator.create_manual = AsyncMock(return_value=doc)
    creator.create_from_description = AsyncMock(return_value=(doc, MagicMock(confidence=0.9)))
    creator.create_from_thread = AsyncMock(return_value=(doc, MagicMock(confidence=0.9)))
    creator.submit_for_approval = AsyncMock(return_value=doc)
    creator.drafter = True  # Truthy to indicate AI is available
    # Approval sub-object
    creator.approval = MagicMock()
    creator.approval.process_decision = AsyncMock(
        return_value=MagicMock(status="approved")
    )
    creator.get_document = MagicMock(return_value=doc)
    return creator


@pytest.mark.asyncio
async def test_manual_document_creation_and_approval(slack_client, db_session, e2e_config):
    """
    Scenario: Manual Document Creation and Approval
    1. Simulate /create-doc modal submission (Manual mode)
    2. Verify document is created as 'published' (for non-policy types)
    3. Simulate Policy creation (requires approval)
    4. Submit for approval
    5. Approve document
    """
    unique_id = uuid.uuid4().hex[:8]
    title = f"E2E Test Doc {unique_id}"

    # 1. Simulate Modal Submission (Manual, GUIDELINE - auto-published)
    ack = AsyncMock()
    mock_client = MagicMock()
    mock_client.chat_postMessage = AsyncMock()
    mock_client.chat_postEphemeral = AsyncMock()

    body = {
        "user": {"id": "U12345"},
        "trigger_id": "trigger_123"
    }
    view = {
        "state": {
            "values": {
                "title_block": {"title_input": {"value": title}},
                "area_block": {"area_select": {"selected_option": {"value": "engineering"}}},
                "type_block": {"type_select": {"selected_option": {"value": "guideline"}}},
                "classification_block": {"classification_select": {"selected_option": {"value": "internal"}}},
                "mode_block": {"mode_select": {"selected_option": {"value": "manual"}}},
                "description_block": {"description_input": {"value": "This is a test guideline content."}}
            }
        }
    }

    # Create mock doc for guideline (auto-published)
    guideline_doc = _make_mock_doc(
        title=title,
        status="published",
        doc_type="guideline",
        area="engineering",
        content="This is a test guideline content.",
        created_by="U12345",
    )
    mock_creator = _make_mock_creator(doc=guideline_doc)

    with patch(_PATCH_INIT_DB, new_callable=AsyncMock), \
         patch(_PATCH_GET_CREATOR, new_callable=AsyncMock, return_value=mock_creator):
        # Call handler
        await handle_create_doc_submit(ack, body, mock_client, view)

    # Verify ack was called
    ack.assert_awaited()
    # Verify create_manual was called with expected args
    mock_creator.create_manual.assert_awaited_once()
    # Verify notification sent
    mock_client.chat_postMessage.assert_awaited()

    # 2. Simulate Policy Creation (Requires Approval)
    policy_title = f"E2E Policy {unique_id}"
    view["state"]["values"]["title_block"]["title_input"]["value"] = policy_title
    view["state"]["values"]["type_block"]["type_select"]["selected_option"]["value"] = "policy"

    policy_doc = _make_mock_doc(
        title=policy_title,
        status="draft",
        doc_type="policy",
        area="engineering",
        content="This is a test guideline content.",
        created_by="U12345",
    )
    mock_creator_policy = _make_mock_creator(doc=policy_doc)

    with patch(_PATCH_INIT_DB, new_callable=AsyncMock), \
         patch(_PATCH_GET_CREATOR, new_callable=AsyncMock, return_value=mock_creator_policy):
        await handle_create_doc_submit(ack, body, mock_client, view)

    mock_creator_policy.create_manual.assert_awaited_once()

    # 3. Submit for Approval
    submit_body = {
        "user": {"id": "U12345"},
        "channel": {"id": "C12345"},
        "actions": [{"action_id": f"submit_doc_{policy_doc.doc_id}"}]
    }

    # After submit, doc status changes to in_review
    submitted_doc = _make_mock_doc(
        doc_id=policy_doc.doc_id,
        title=policy_title,
        status="in_review",
        doc_type="policy",
        area="engineering",
        created_by="U12345",
    )
    mock_creator_submit = _make_mock_creator(doc=submitted_doc)
    mock_creator_submit.submit_for_approval = AsyncMock(return_value=submitted_doc)

    with patch(_PATCH_INIT_DB, new_callable=AsyncMock), \
         patch(_PATCH_GET_CREATOR, new_callable=AsyncMock, return_value=mock_creator_submit):
        await handle_submit_for_approval(ack, submit_body, mock_client)

    mock_creator_submit.submit_for_approval.assert_awaited_once()
    mock_client.chat_postEphemeral.assert_awaited()

    # 4. Approve
    approve_body = {
        "user": {"id": "U_APPROVER"},
        "channel": {"id": "C12345"},
        "actions": [{"action_id": f"approve_doc_{policy_doc.doc_id}"}]
    }

    approval_status = MagicMock(status="approved")
    mock_creator_approve = _make_mock_creator(doc=policy_doc)
    mock_creator_approve.approval.process_decision = AsyncMock(return_value=approval_status)

    with patch(_PATCH_INIT_DB, new_callable=AsyncMock), \
         patch(_PATCH_GET_CREATOR, new_callable=AsyncMock, return_value=mock_creator_approve):
        await handle_approve_doc(ack, approve_body, mock_client)

    mock_creator_approve.approval.process_decision.assert_awaited_once()
    mock_client.chat_postEphemeral.assert_awaited()


@pytest.mark.asyncio
async def test_save_thread_as_doc_flow(slack_client, db_session, e2e_config):
    """
    Scenario: Save Thread as Doc
    1. Simulate thread-to-doc modal submission
    2. Verify AI drafter is called (mocked)
    3. Verify document is created
    """
    unique_id = uuid.uuid4().hex[:8]
    title = f"Thread Doc {unique_id}"

    from knowledge_base.slack.doc_creation import handle_thread_to_doc_submit
    import json

    ack = AsyncMock()
    mock_client = MagicMock()
    mock_client.chat_postMessage = AsyncMock()

    # Mock thread replies - must be AsyncMock since handler awaits it
    mock_client.conversations_replies = AsyncMock(return_value={
        "ok": True,
        "messages": [
            {"user": "U1", "text": "We should implement feature X", "ts": "100.1"},
            {"user": "U2", "text": "Yes, using library Y", "ts": "100.2"},
            {"user": "U1", "text": "Agreed. Let's document this.", "ts": "100.3"},
        ]
    })

    body = {
        "user": {"id": "U12345"},
    }
    view = {
        "private_metadata": json.dumps({
            "channel_id": "C_TEST",
            "thread_ts": "100.1"
        }),
        "state": {
            "values": {
                "area_block": {"area_select": {"selected_option": {"value": "engineering"}}},
                "type_block": {"type_select": {"selected_option": {"value": "information"}}},
                "classification_block": {"classification_select": {"selected_option": {"value": "internal"}}},
            }
        }
    }

    # Create mock doc for thread-to-doc result
    thread_doc = _make_mock_doc(
        title=title,
        status="published",
        doc_type="information",
        area="engineering",
        content="Summary of discussion about feature X using library Y.",
        created_by="U12345",
    )
    mock_draft_result = MagicMock(confidence=0.85)
    mock_creator = _make_mock_creator(doc=thread_doc)
    mock_creator.create_from_thread = AsyncMock(return_value=(thread_doc, mock_draft_result))
    mock_creator.drafter = True  # AI is available

    with patch(_PATCH_INIT_DB, new_callable=AsyncMock), \
         patch(_PATCH_GET_CREATOR, new_callable=AsyncMock, return_value=mock_creator):
        # Call handler
        await handle_thread_to_doc_submit(ack, body, mock_client, view)

    # Verify ack was called
    ack.assert_awaited()
    # Verify thread messages were fetched
    mock_client.conversations_replies.assert_awaited_once()
    # Verify create_from_thread was called
    mock_creator.create_from_thread.assert_awaited_once()
    # Verify notification sent
    mock_client.chat_postMessage.assert_awaited()
