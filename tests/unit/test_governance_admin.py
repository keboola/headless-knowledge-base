"""Tests for governance admin Slack interface (notifications + button handlers)."""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# The default KNOWLEDGE_ADMIN_CHANNEL is "#knowledge-admins".
# _get_admin_channel() strips the '#', yielding "knowledge-admins".
# We use that as the default channel_id in test bodies so the auth check passes.
_ADMIN_CHANNEL_ID = "knowledge-admins"


# ---------------------------------------------------------------------------
# Helpers: mock record objects
# ---------------------------------------------------------------------------

def _make_record(
    chunk_id: str = "chunk_abc123",
    risk_score: float = 80.0,
    risk_tier: str = "high",
    risk_factors: str | None = None,
    intake_path: str = "slack_ingest",
    submitted_by: str = "user@keboola.com",
    content_preview: str = "This is a preview of the content for testing purposes.",
    status: str = "pending_review",
    revert_deadline: datetime | None = None,
    slack_notification_ts: str | None = None,
    slack_notification_channel: str | None = None,
) -> SimpleNamespace:
    """Build a lightweight mock of KnowledgeGovernanceRecord."""
    if risk_factors is None:
        risk_factors = json.dumps({
            "author_trust": 10.0,
            "source_type": 70.0,
            "content_scope": 35.0,
            "novelty": 20.0,
            "contradiction": 20.0,
        })
    return SimpleNamespace(
        chunk_id=chunk_id,
        risk_score=risk_score,
        risk_tier=risk_tier,
        risk_factors=risk_factors,
        intake_path=intake_path,
        submitted_by=submitted_by,
        content_preview=content_preview,
        status=status,
        revert_deadline=revert_deadline,
        slack_notification_ts=slack_notification_ts,
        slack_notification_channel=slack_notification_channel,
    )


def _make_body(
    action_id: str,
    user_id: str = "U_ADMIN_1",
    channel_id: str = _ADMIN_CHANNEL_ID,
    message_ts: str = "1234567890.123456",
    trigger_id: str = "trigger_abc",
) -> dict:
    """Build a mock Slack action body."""
    return {
        "user": {"id": user_id},
        "channel": {"id": channel_id},
        "message": {"ts": message_ts},
        "actions": [{"action_id": action_id}],
        "trigger_id": trigger_id,
    }


def _patch_db_update():
    """Patch the DB session maker import used inside notify functions.

    The governance_admin module imports async_session_maker inside the function
    body, so we need to patch it on the db.database module.
    """
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    mock_session.commit = AsyncMock()

    return patch(
        "knowledge_base.db.database.async_session_maker",
        return_value=mock_session,
    )


# ---------------------------------------------------------------------------
# Tests: notify_admin_high_risk
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_high_risk_notification_has_approve_reject_buttons():
    """Verify high-risk notification posts message with Approve and Reject buttons."""
    from knowledge_base.slack.governance_admin import notify_admin_high_risk

    record = _make_record(risk_tier="high", risk_score=85.0)

    mock_client = AsyncMock()
    mock_client.chat_postMessage.return_value = {"ts": "1111.2222", "channel": "C_ADM"}

    with _patch_db_update():
        ts = await notify_admin_high_risk(mock_client, record)

    assert ts == "1111.2222"
    mock_client.chat_postMessage.assert_called_once()

    call_kwargs = mock_client.chat_postMessage.call_args.kwargs
    blocks = call_kwargs["blocks"]

    # Verify header
    headers = [b for b in blocks if b.get("type") == "header"]
    assert len(headers) == 1
    assert "Approval Request" in headers[0]["text"]["text"]

    # Verify action buttons
    action_blocks = [b for b in blocks if b.get("type") == "actions"]
    assert len(action_blocks) == 1

    buttons = action_blocks[0]["elements"]
    action_ids = [btn["action_id"] for btn in buttons]
    assert f"governance_approve_{record.chunk_id}" in action_ids
    assert f"governance_reject_{record.chunk_id}" in action_ids


@pytest.mark.asyncio
async def test_high_risk_notification_includes_risk_factors():
    """Verify risk factors are rendered in the notification."""
    from knowledge_base.slack.governance_admin import notify_admin_high_risk

    record = _make_record()
    mock_client = AsyncMock()
    mock_client.chat_postMessage.return_value = {"ts": "1111.2222", "channel": "C_ADM"}

    with _patch_db_update():
        await notify_admin_high_risk(mock_client, record)

    call_kwargs = mock_client.chat_postMessage.call_args.kwargs
    blocks = call_kwargs["blocks"]

    # Find section block containing risk factors
    risk_blocks = [
        b for b in blocks
        if b.get("type") == "section"
        and "Risk Factors" in (b.get("text", {}).get("text", ""))
    ]
    assert len(risk_blocks) == 1
    text = risk_blocks[0]["text"]["text"]
    assert "Author Trust" in text
    assert "Source Type" in text


@pytest.mark.asyncio
async def test_high_risk_notification_failure_returns_none():
    """Verify None is returned on Slack API failure."""
    from knowledge_base.slack.governance_admin import notify_admin_high_risk

    record = _make_record()
    mock_client = AsyncMock()
    mock_client.chat_postMessage.side_effect = Exception("Slack API error")

    ts = await notify_admin_high_risk(mock_client, record)
    assert ts is None


# ---------------------------------------------------------------------------
# Tests: notify_admin_medium_risk
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_medium_risk_notification_has_revert_button():
    """Verify medium-risk notification has Revert and Mark Reviewed buttons."""
    from knowledge_base.slack.governance_admin import notify_admin_medium_risk

    deadline = datetime.utcnow() + timedelta(hours=24)
    record = _make_record(
        risk_tier="medium",
        risk_score=50.0,
        status="auto_approved",
        revert_deadline=deadline,
    )

    mock_client = AsyncMock()
    mock_client.chat_postMessage.return_value = {"ts": "3333.4444", "channel": "C_ADM"}

    with _patch_db_update():
        ts = await notify_admin_medium_risk(mock_client, record)

    assert ts == "3333.4444"
    mock_client.chat_postMessage.assert_called_once()

    call_kwargs = mock_client.chat_postMessage.call_args.kwargs
    blocks = call_kwargs["blocks"]

    # Verify header
    headers = [b for b in blocks if b.get("type") == "header"]
    assert "Auto-Approved" in headers[0]["text"]["text"]

    # Verify action buttons
    action_blocks = [b for b in blocks if b.get("type") == "actions"]
    assert len(action_blocks) == 1

    buttons = action_blocks[0]["elements"]
    action_ids = [btn["action_id"] for btn in buttons]
    assert f"governance_revert_{record.chunk_id}" in action_ids
    assert f"governance_mark_reviewed_{record.chunk_id}" in action_ids

    # Verify revert deadline is shown
    all_text = json.dumps(blocks)
    assert "Revert Deadline" in all_text


# ---------------------------------------------------------------------------
# Tests: handle_governance_approve
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_handler_calls_engine():
    """Verify engine.approve is called with correct chunk_id and user."""
    from knowledge_base.slack.governance_admin import handle_governance_approve

    body = _make_body("governance_approve_chunk123")
    mock_ack = AsyncMock()
    mock_client = AsyncMock()

    mock_engine_instance = AsyncMock()
    mock_engine_instance.approve.return_value = True

    with patch(
        "knowledge_base.governance.approval_engine.ApprovalEngine",
    ) as mock_engine_cls:
        mock_engine_cls.return_value = mock_engine_instance
        await handle_governance_approve(mock_ack, body, mock_client)

    mock_ack.assert_awaited_once()
    mock_engine_instance.approve.assert_awaited_once_with(
        "chunk123", reviewed_by="U_ADMIN_1"
    )


@pytest.mark.asyncio
async def test_approve_handler_updates_message():
    """Verify chat_update is called to replace buttons with Approved text."""
    from knowledge_base.slack.governance_admin import handle_governance_approve

    body = _make_body("governance_approve_chunk456")
    mock_ack = AsyncMock()
    mock_client = AsyncMock()

    mock_engine_instance = AsyncMock()
    mock_engine_instance.approve.return_value = True

    with patch(
        "knowledge_base.governance.approval_engine.ApprovalEngine",
    ) as mock_engine_cls:
        mock_engine_cls.return_value = mock_engine_instance
        await handle_governance_approve(mock_ack, body, mock_client)

    mock_client.chat_update.assert_awaited_once()
    call_kwargs = mock_client.chat_update.call_args.kwargs
    assert call_kwargs["channel"] == _ADMIN_CHANNEL_ID
    assert call_kwargs["ts"] == "1234567890.123456"
    # Verify "Approved" appears in the updated blocks
    blocks_text = json.dumps(call_kwargs["blocks"])
    assert "Approved" in blocks_text
    assert "an admin" in blocks_text


@pytest.mark.asyncio
async def test_approve_handler_not_pending_sends_ephemeral():
    """When engine.approve returns False, post ephemeral instead of updating."""
    from knowledge_base.slack.governance_admin import handle_governance_approve

    body = _make_body("governance_approve_chunk789")
    mock_ack = AsyncMock()
    mock_client = AsyncMock()

    mock_engine_instance = AsyncMock()
    mock_engine_instance.approve.return_value = False

    with patch(
        "knowledge_base.governance.approval_engine.ApprovalEngine",
    ) as mock_engine_cls:
        mock_engine_cls.return_value = mock_engine_instance
        await handle_governance_approve(mock_ack, body, mock_client)

    mock_client.chat_update.assert_not_awaited()
    mock_client.chat_postEphemeral.assert_awaited_once()


# ---------------------------------------------------------------------------
# Tests: handle_governance_reject (opens modal)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reject_handler_opens_modal():
    """Verify reject button click opens a modal with text input."""
    from knowledge_base.slack.governance_admin import handle_governance_reject

    body = _make_body("governance_reject_chunk_xyz")
    mock_ack = AsyncMock()
    mock_client = AsyncMock()

    await handle_governance_reject(mock_ack, body, mock_client)

    mock_ack.assert_awaited_once()
    mock_client.views_open.assert_awaited_once()

    call_kwargs = mock_client.views_open.call_args.kwargs
    view = call_kwargs["view"]
    assert view["callback_id"] == "governance_reject_modal"
    assert view["private_metadata"] == "chunk_xyz"
    assert view["type"] == "modal"

    # Verify there is an input block for rejection reason
    input_blocks = [b for b in view["blocks"] if b.get("type") == "input"]
    assert len(input_blocks) == 1
    assert input_blocks[0]["block_id"] == "rejection_reason_block"


# ---------------------------------------------------------------------------
# Tests: handle_governance_reject_submit (modal submit)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reject_modal_submit_calls_engine():
    """Verify modal submission calls engine.reject with correct args."""
    from knowledge_base.slack.governance_admin import handle_governance_reject_submit

    mock_ack = AsyncMock()
    mock_client = AsyncMock()

    body = {"user": {"id": "U_ADMIN_2"}}
    view = {
        "private_metadata": "chunk_submit_test",
        "state": {
            "values": {
                "rejection_reason_block": {
                    "rejection_reason": {
                        "value": "Content is inaccurate",
                    }
                }
            }
        },
    }

    mock_engine_instance = AsyncMock()
    mock_engine_instance.reject.return_value = True

    with patch(
        "knowledge_base.governance.approval_engine.ApprovalEngine",
    ) as mock_engine_cls:
        mock_engine_cls.return_value = mock_engine_instance
        await handle_governance_reject_submit(mock_ack, body, view, mock_client)

    mock_ack.assert_awaited_once()
    mock_engine_instance.reject.assert_awaited_once_with(
        "chunk_submit_test",
        reviewed_by="U_ADMIN_2",
        note="Content is inaccurate",
    )

    # Should post confirmation to admin channel
    mock_client.chat_postMessage.assert_awaited_once()
    msg_text = mock_client.chat_postMessage.call_args.kwargs["text"]
    assert "Rejected" in msg_text
    assert "chunk_submit_test" in msg_text


# ---------------------------------------------------------------------------
# Tests: handle_governance_revert (opens confirmation modal)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revert_handler_opens_confirmation_modal():
    """Verify revert button click opens a confirmation modal."""
    from knowledge_base.slack.governance_admin import handle_governance_revert

    body = _make_body("governance_revert_chunk_rev1")
    mock_ack = AsyncMock()
    mock_client = AsyncMock()

    await handle_governance_revert(mock_ack, body, mock_client)

    mock_ack.assert_awaited_once()
    mock_client.views_open.assert_awaited_once()

    call_kwargs = mock_client.views_open.call_args.kwargs
    view = call_kwargs["view"]
    assert view["callback_id"] == "governance_revert_modal"
    assert view["type"] == "modal"

    # Verify private_metadata contains chunk_id, channel_id, message_ts
    meta = json.loads(view["private_metadata"])
    assert meta["chunk_id"] == "chunk_rev1"
    assert meta["channel_id"] == _ADMIN_CHANNEL_ID
    assert meta["message_ts"] == "1234567890.123456"

    # Verify confirmation text
    section_blocks = [b for b in view["blocks"] if b.get("type") == "section"]
    assert len(section_blocks) == 1
    assert "Are you sure" in section_blocks[0]["text"]["text"]
    assert "unsearchable" in section_blocks[0]["text"]["text"]

    # Verify optional note input
    input_blocks = [b for b in view["blocks"] if b.get("type") == "input"]
    assert len(input_blocks) == 1
    assert input_blocks[0]["block_id"] == "revert_note_block"
    assert input_blocks[0]["optional"] is True


# ---------------------------------------------------------------------------
# Tests: handle_governance_revert_submit (modal submit)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revert_submit_calls_engine():
    """Verify revert modal submission calls engine.revert and updates message."""
    from knowledge_base.slack.governance_admin import handle_governance_revert_submit

    mock_ack = AsyncMock()
    mock_client = AsyncMock()

    body = {"user": {"id": "U_ADMIN_1"}}
    view = {
        "private_metadata": json.dumps({
            "chunk_id": "chunk_rev1",
            "channel_id": _ADMIN_CHANNEL_ID,
            "message_ts": "1234567890.123456",
        }),
        "state": {
            "values": {
                "revert_note_block": {
                    "revert_note": {
                        "value": "Content was wrong",
                    }
                }
            }
        },
    }

    mock_engine_instance = AsyncMock()
    mock_engine_instance.revert.return_value = True

    with patch(
        "knowledge_base.governance.approval_engine.ApprovalEngine",
    ) as mock_engine_cls:
        mock_engine_cls.return_value = mock_engine_instance
        await handle_governance_revert_submit(mock_ack, body, view, mock_client)

    mock_ack.assert_awaited_once()
    mock_engine_instance.revert.assert_awaited_once_with(
        "chunk_rev1", reviewed_by="U_ADMIN_1"
    )

    # Should update the original message to show reverted
    mock_client.chat_update.assert_awaited_once()
    call_kwargs = mock_client.chat_update.call_args.kwargs
    assert call_kwargs["channel"] == _ADMIN_CHANNEL_ID
    assert call_kwargs["ts"] == "1234567890.123456"
    blocks_text = json.dumps(call_kwargs["blocks"])
    assert "Reverted" in blocks_text


@pytest.mark.asyncio
async def test_revert_submit_window_expired():
    """When engine.revert returns False, post message about expired window."""
    from knowledge_base.slack.governance_admin import handle_governance_revert_submit

    mock_ack = AsyncMock()
    mock_client = AsyncMock()

    body = {"user": {"id": "U_ADMIN_1"}}
    view = {
        "private_metadata": json.dumps({
            "chunk_id": "chunk_rev2",
            "channel_id": _ADMIN_CHANNEL_ID,
            "message_ts": "1234567890.123456",
        }),
        "state": {
            "values": {
                "revert_note_block": {
                    "revert_note": {
                        "value": None,
                    }
                }
            }
        },
    }

    mock_engine_instance = AsyncMock()
    mock_engine_instance.revert.return_value = False

    with patch(
        "knowledge_base.governance.approval_engine.ApprovalEngine",
    ) as mock_engine_cls:
        mock_engine_cls.return_value = mock_engine_instance
        await handle_governance_revert_submit(mock_ack, body, view, mock_client)

    mock_client.chat_update.assert_not_awaited()
    mock_client.chat_postMessage.assert_awaited_once()
    msg_text = mock_client.chat_postMessage.call_args.kwargs["text"]
    assert "expired" in msg_text.lower()


# ---------------------------------------------------------------------------
# Tests: handle_governance_mark_reviewed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_reviewed_updates_message():
    """Verify mark-reviewed updates the Slack message with Reviewed text."""
    from knowledge_base.slack.governance_admin import handle_governance_mark_reviewed

    body = _make_body("governance_mark_reviewed_chunk_mr1")
    mock_ack = AsyncMock()
    mock_client = AsyncMock()

    await handle_governance_mark_reviewed(mock_ack, body, mock_client)

    mock_ack.assert_awaited_once()
    mock_client.chat_update.assert_awaited_once()

    call_kwargs = mock_client.chat_update.call_args.kwargs
    blocks_text = json.dumps(call_kwargs["blocks"])
    assert "Reviewed" in blocks_text
    assert "an admin" in blocks_text


# ---------------------------------------------------------------------------
# Tests: Authorization -- actions from non-admin channels are rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_rejects_non_admin_channel():
    """Actions from non-admin channels should be rejected with ephemeral message."""
    from knowledge_base.slack.governance_admin import handle_governance_approve

    body = _make_body("governance_approve_chunk123", channel_id="C_RANDOM_CH")
    mock_ack = AsyncMock()
    mock_client = AsyncMock()

    await handle_governance_approve(mock_ack, body, mock_client)

    mock_ack.assert_awaited_once()
    # Should NOT call the approval engine
    mock_client.chat_update.assert_not_awaited()
    # Should post ephemeral rejection
    mock_client.chat_postEphemeral.assert_awaited_once()
    text = mock_client.chat_postEphemeral.call_args.kwargs["text"]
    assert "admin channel" in text.lower()


@pytest.mark.asyncio
async def test_reject_rejects_non_admin_channel():
    """Reject button from non-admin channel should be rejected."""
    from knowledge_base.slack.governance_admin import handle_governance_reject

    body = _make_body("governance_reject_chunk123", channel_id="C_RANDOM_CH")
    mock_ack = AsyncMock()
    mock_client = AsyncMock()

    await handle_governance_reject(mock_ack, body, mock_client)

    mock_ack.assert_awaited_once()
    mock_client.views_open.assert_not_awaited()
    mock_client.chat_postEphemeral.assert_awaited_once()
    text = mock_client.chat_postEphemeral.call_args.kwargs["text"]
    assert "admin channel" in text.lower()


@pytest.mark.asyncio
async def test_revert_rejects_non_admin_channel():
    """Revert button from non-admin channel should be rejected."""
    from knowledge_base.slack.governance_admin import handle_governance_revert

    body = _make_body("governance_revert_chunk123", channel_id="C_RANDOM_CH")
    mock_ack = AsyncMock()
    mock_client = AsyncMock()

    await handle_governance_revert(mock_ack, body, mock_client)

    mock_ack.assert_awaited_once()
    mock_client.views_open.assert_not_awaited()
    mock_client.chat_postEphemeral.assert_awaited_once()
    text = mock_client.chat_postEphemeral.call_args.kwargs["text"]
    assert "admin channel" in text.lower()


@pytest.mark.asyncio
async def test_mark_reviewed_rejects_non_admin_channel():
    """Mark reviewed from non-admin channel should be rejected."""
    from knowledge_base.slack.governance_admin import handle_governance_mark_reviewed

    body = _make_body("governance_mark_reviewed_chunk123", channel_id="C_RANDOM_CH")
    mock_ack = AsyncMock()
    mock_client = AsyncMock()

    await handle_governance_mark_reviewed(mock_ack, body, mock_client)

    mock_ack.assert_awaited_once()
    mock_client.chat_update.assert_not_awaited()
    mock_client.chat_postEphemeral.assert_awaited_once()
    text = mock_client.chat_postEphemeral.call_args.kwargs["text"]
    assert "admin channel" in text.lower()


# ---------------------------------------------------------------------------
# Tests: handle_governance_queue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_governance_queue_with_pending_items():
    """Verify queue command shows pending and revertable items."""
    from knowledge_base.slack.governance_admin import handle_governance_queue

    mock_ack = AsyncMock()
    mock_client = AsyncMock()

    pending = [
        _make_record(chunk_id="pending_1", risk_score=80, risk_tier="high"),
        _make_record(chunk_id="pending_2", risk_score=75, risk_tier="high"),
    ]
    revertable = [
        _make_record(
            chunk_id="revert_1",
            risk_tier="medium",
            risk_score=50,
            status="auto_approved",
            revert_deadline=datetime.utcnow() + timedelta(hours=12),
        ),
    ]

    mock_engine_instance = AsyncMock()
    mock_engine_instance.get_pending_queue.return_value = pending
    mock_engine_instance.get_revertable_items.return_value = revertable

    command = {"user_id": "U_CMD_USER", "channel_id": "C_CMD_CH"}

    with patch(
        "knowledge_base.governance.approval_engine.ApprovalEngine",
    ) as mock_engine_cls:
        mock_engine_cls.return_value = mock_engine_instance
        await handle_governance_queue(mock_ack, command, mock_client)

    mock_ack.assert_awaited_once()
    mock_client.chat_postEphemeral.assert_awaited_once()

    call_kwargs = mock_client.chat_postEphemeral.call_args.kwargs
    blocks = call_kwargs["blocks"]

    # Should contain headers for both sections
    header_texts = [
        b["text"]["text"]
        for b in blocks
        if b.get("type") == "header"
    ]
    assert any("Pending" in h for h in header_texts)
    assert any("Revertable" in h for h in header_texts)

    # Should contain approve/reject buttons for pending items
    all_action_ids = []
    for b in blocks:
        if b.get("type") == "actions":
            for el in b.get("elements", []):
                all_action_ids.append(el["action_id"])

    assert "governance_approve_pending_1" in all_action_ids
    assert "governance_reject_pending_2" in all_action_ids
    assert "governance_revert_revert_1" in all_action_ids


@pytest.mark.asyncio
async def test_governance_queue_empty():
    """Verify queue command shows 'No pending items' when empty."""
    from knowledge_base.slack.governance_admin import handle_governance_queue

    mock_ack = AsyncMock()
    mock_client = AsyncMock()

    mock_engine_instance = AsyncMock()
    mock_engine_instance.get_pending_queue.return_value = []
    mock_engine_instance.get_revertable_items.return_value = []

    command = {"user_id": "U_CMD_USER", "channel_id": "C_CMD_CH"}

    with patch(
        "knowledge_base.governance.approval_engine.ApprovalEngine",
    ) as mock_engine_cls:
        mock_engine_cls.return_value = mock_engine_instance
        await handle_governance_queue(mock_ack, command, mock_client)

    mock_ack.assert_awaited_once()
    mock_client.chat_postEphemeral.assert_awaited_once()

    call_kwargs = mock_client.chat_postEphemeral.call_args.kwargs
    assert "No pending items" in call_kwargs["text"]
    # Should not have blocks when empty
    assert "blocks" not in call_kwargs


# ---------------------------------------------------------------------------
# Tests: register_governance_handlers
# ---------------------------------------------------------------------------


def test_register_governance_handlers():
    """Verify register_governance_handlers registers all expected handlers."""
    from knowledge_base.slack.governance_admin import register_governance_handlers

    mock_app = MagicMock()

    register_governance_handlers(mock_app)

    # 4 action registrations + 2 views (reject + revert) + 1 command = 7 total
    assert mock_app.action.call_count == 4
    assert mock_app.view.call_count == 2
    assert mock_app.command.call_count == 1

    # Verify both view callback_ids were registered
    view_calls = [call[0][0] for call in mock_app.view.call_args_list]
    assert "governance_reject_modal" in view_calls
    assert "governance_revert_modal" in view_calls

    # Verify the command name includes prefix
    cmd_call_args = mock_app.command.call_args
    cmd_name = cmd_call_args[0][0]
    assert "governance-queue" in cmd_name


# ---------------------------------------------------------------------------
# Tests: _format_risk_factors helper
# ---------------------------------------------------------------------------


def test_format_risk_factors_valid_json():
    """Verify risk factors formatting from valid JSON."""
    from knowledge_base.slack.governance_admin import _format_risk_factors

    factors_json = json.dumps({"author_trust": 10.0, "source_type": 70.0})
    result = _format_risk_factors(factors_json)
    assert "Author Trust: 10/100" in result
    assert "Source Type: 70/100" in result


def test_format_risk_factors_invalid_json():
    """Verify graceful handling of invalid JSON."""
    from knowledge_base.slack.governance_admin import _format_risk_factors

    result = _format_risk_factors("not valid json {{{")
    assert "No risk factors" in result


def test_format_risk_factors_empty():
    """Verify graceful handling of empty dict."""
    from knowledge_base.slack.governance_admin import _format_risk_factors

    result = _format_risk_factors("{}")
    assert "No risk factors" in result
