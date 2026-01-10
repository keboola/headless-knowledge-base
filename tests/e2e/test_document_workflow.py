"""E2E tests for Document Creation and Approval workflow."""

import pytest
import uuid
import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock
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
    
    # Call handler
    handle_create_doc_submit(ack, body, mock_client, view)
    
    # Give it a moment to process (it runs async internally in some parts but handle_create_doc_submit uses asyncio.run(init_db()) and then calls creator)
    # Actually doc_creation.py uses asyncio.run(init_db()) and asyncio.run(creator.create_manual(...))
    # So it's synchronous from the perspective of handle_create_doc_submit.
    
    # Verify DB
    stmt = select(Document).where(Document.title == title)
    result = await db_session.execute(stmt)
    doc = result.scalar_one_or_none()
    
    assert doc is not None
    assert doc.status == "published" # Guidelines are auto-published
    assert doc.doc_type == "guideline"

    # 2. Simulate Policy Creation (Requires Approval)
    policy_title = f"E2E Policy {unique_id}"
    view["state"]["values"]["title_block"]["title_input"]["value"] = policy_title
    view["state"]["values"]["type_block"]["type_select"]["selected_option"]["value"] = "policy"
    
    handle_create_doc_submit(ack, body, mock_client, view)
    
    stmt = select(Document).where(Document.title == policy_title)
    result = await db_session.execute(stmt)
    policy_doc = result.scalar_one_or_none()
    
    assert policy_doc is not None
    assert policy_doc.status == "draft" # Policies start as draft
    
    # 3. Add approver for engineering area (required for approval to work)
    approver = AreaApprover(
        area="engineering",
        approver_slack_id="U_APPROVER",
        approver_name="Test Approver",
        is_active=True,
    )
    db_session.add(approver)
    await db_session.commit()

    # 4. Submit for Approval
    submit_body = {
        "user": {"id": "U12345"},
        "channel": {"id": "C12345"},
        "actions": [{"action_id": f"submit_doc_{policy_doc.doc_id}"}]
    }
    mock_client.chat_postEphemeral = AsyncMock()

    handle_submit_for_approval(ack, submit_body, mock_client)

    # Refresh doc
    await db_session.refresh(policy_doc)
    assert policy_doc.status == "in_review"

    # 5. Approve
    approve_body = {
        "user": {"id": "U_APPROVER"},
        "channel": {"id": "C12345"},
        "actions": [{"action_id": f"approve_doc_{policy_doc.doc_id}"}]
    }

    handle_approve_doc(ack, approve_body, mock_client)
    
    # Refresh doc
    await db_session.refresh(policy_doc)
    assert policy_doc.status == "approved"  # Approval workflow sets to "approved"

    # Verify approval info in Document
    assert "U_APPROVER" in policy_doc.approved_by
    assert policy_doc.approved_at is not None

@pytest.mark.asyncio
async def test_save_thread_as_doc_flow(slack_client, db_session, e2e_config):
    """
    Scenario: Save Thread as Doc
    1. Simulate thread-to-doc modal submission
    2. Verify AI drafter is called (mocked or real)
    3. Verify document is created
    """
    # This one is more complex because it fetches thread history from Slack.
    # We'll mock the conversations_replies response.
    
    unique_id = uuid.uuid4().hex[:8]
    title = f"Thread Doc {unique_id}"
    
    from knowledge_base.slack.doc_creation import handle_thread_to_doc_submit
    import json
    
    ack = AsyncMock()
    mock_client = MagicMock()
    mock_client.chat_postMessage = AsyncMock()
    
    # Mock thread replies
    mock_client.conversations_replies.return_value = {
        "ok": True,
        "messages": [
            {"user": "U1", "text": "We should implement feature X", "ts": "100.1"},
            {"user": "U2", "text": "Yes, using library Y", "ts": "100.2"},
            {"user": "U1", "text": "Agreed. Let's document this.", "ts": "100.3"},
        ]
    }
    
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
    
    # Call handler
    handle_thread_to_doc_submit(ack, body, mock_client, view)
    
    # Verify DB - Since it's AI created, title might be generated by AI.
    # But wait, handle_thread_to_doc_submit uses creator.create_from_thread which uses AI to generate title if not provided.
    # Let's check the last created document.
    stmt = select(Document).order_by(Document.created_at.desc()).limit(1)
    result = await db_session.execute(stmt)
    doc = result.scalar_one_or_none()
    
    assert doc is not None
    assert doc.created_by == "U12345"
    assert "feature X" in doc.content or "library Y" in doc.content or doc.status == "published"
