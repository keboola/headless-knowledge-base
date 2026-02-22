"""Tests for async document creation Slack handlers."""

import inspect
import json
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from knowledge_base.slack.doc_creation import (
    _get_document_creator,
    handle_approve_doc,
    handle_create_doc_command,
    handle_create_doc_submit,
    handle_edit_doc,
    handle_reject_doc,
    handle_rejection_submit,
    handle_save_as_doc,
    handle_submit_for_approval,
    handle_thread_to_doc_submit,
    handle_view_doc,
    register_doc_handlers,
)


# =============================================================================
# All handlers must be async coroutines
# =============================================================================


class TestHandlersAreAsync:
    """Verify all handlers are async — required for Slack Bolt AsyncApp."""

    def test_handle_create_doc_command_is_async(self):
        assert inspect.iscoroutinefunction(handle_create_doc_command)

    def test_handle_save_as_doc_is_async(self):
        assert inspect.iscoroutinefunction(handle_save_as_doc)

    def test_handle_create_doc_submit_is_async(self):
        assert inspect.iscoroutinefunction(handle_create_doc_submit)

    def test_handle_thread_to_doc_submit_is_async(self):
        assert inspect.iscoroutinefunction(handle_thread_to_doc_submit)

    def test_handle_rejection_submit_is_async(self):
        assert inspect.iscoroutinefunction(handle_rejection_submit)

    def test_handle_approve_doc_is_async(self):
        assert inspect.iscoroutinefunction(handle_approve_doc)

    def test_handle_reject_doc_is_async(self):
        assert inspect.iscoroutinefunction(handle_reject_doc)

    def test_handle_submit_for_approval_is_async(self):
        assert inspect.iscoroutinefunction(handle_submit_for_approval)

    def test_handle_view_doc_is_async(self):
        assert inspect.iscoroutinefunction(handle_view_doc)

    def test_handle_edit_doc_is_async(self):
        assert inspect.iscoroutinefunction(handle_edit_doc)

    def test_get_document_creator_is_async(self):
        assert inspect.iscoroutinefunction(_get_document_creator)


# =============================================================================
# Handler behavior tests
# =============================================================================


@pytest.mark.asyncio
class TestCreateDocCommand:
    """Tests for /create-doc slash command handler."""

    async def test_acks_and_opens_modal(self):
        ack = AsyncMock()
        client = AsyncMock()
        body = {"trigger_id": "T123"}

        await handle_create_doc_command(ack=ack, body=body, client=client)

        ack.assert_awaited_once()
        client.views_open.assert_awaited_once()
        call_kwargs = client.views_open.call_args[1]
        assert call_kwargs["trigger_id"] == "T123"

    async def test_handles_error_gracefully(self):
        ack = AsyncMock()
        client = AsyncMock()
        client.views_open.side_effect = Exception("Slack API error")
        body = {"trigger_id": "T123"}

        # Should not raise
        await handle_create_doc_command(ack=ack, body=body, client=client)
        ack.assert_awaited_once()


@pytest.mark.asyncio
class TestSaveAsDoc:
    """Tests for Save as Doc message shortcut handler."""

    async def test_acks_and_opens_modal(self):
        ack = AsyncMock()
        client = AsyncMock()
        shortcut = {
            "trigger_id": "T456",
            "channel": {"id": "C123"},
            "message": {"ts": "1234567890.123456", "thread_ts": "1234567890.000000"},
        }

        await handle_save_as_doc(ack=ack, shortcut=shortcut, client=client)

        ack.assert_awaited_once()
        client.views_open.assert_awaited_once()


@pytest.mark.asyncio
class TestEditDoc:
    """Tests for edit document button handler."""

    async def test_acks_and_sends_ephemeral(self):
        ack = AsyncMock()
        client = AsyncMock()
        body = {
            "user": {"id": "U123"},
            "actions": [{"action_id": "edit_doc_DOC001"}],
            "channel": {"id": "C123"},
        }

        await handle_edit_doc(ack=ack, body=body, client=client)

        ack.assert_awaited_once()
        client.chat_postEphemeral.assert_awaited_once()
        call_kwargs = client.chat_postEphemeral.call_args[1]
        assert "DOC001" in call_kwargs["text"]
        assert call_kwargs["channel"] == "C123"
        assert call_kwargs["user"] == "U123"


@pytest.mark.asyncio
class TestApproveDoc:
    """Tests for document approval handler."""

    @patch("knowledge_base.slack.doc_creation.init_db", new_callable=AsyncMock)
    @patch("knowledge_base.slack.doc_creation._get_document_creator")
    async def test_acks_and_processes_approval(self, mock_creator_fn, mock_init_db):
        mock_creator = MagicMock()
        mock_creator.approval.process_decision = AsyncMock(
            return_value=MagicMock(status="approved")
        )
        mock_creator_fn.return_value = mock_creator

        ack = AsyncMock()
        client = AsyncMock()
        body = {
            "user": {"id": "U123"},
            "actions": [{"action_id": "approve_doc_DOC001"}],
            "channel": {"id": "C123"},
        }

        await handle_approve_doc(ack=ack, body=body, client=client)

        ack.assert_awaited_once()
        mock_init_db.assert_awaited_once()
        client.chat_postEphemeral.assert_awaited_once()


@pytest.mark.asyncio
class TestRejectDoc:
    """Tests for document rejection button handler."""

    @patch("knowledge_base.slack.doc_creation.init_db", new_callable=AsyncMock)
    @patch("knowledge_base.slack.doc_creation._get_document_creator")
    async def test_acks_and_opens_rejection_modal(self, mock_creator_fn, mock_init_db):
        mock_doc = MagicMock()
        mock_doc.title = "Test Document"
        mock_creator = MagicMock()
        mock_creator.get_document.return_value = mock_doc
        mock_creator_fn.return_value = mock_creator

        ack = AsyncMock()
        client = AsyncMock()
        body = {
            "actions": [{"action_id": "reject_doc_DOC001"}],
            "trigger_id": "T789",
        }

        await handle_reject_doc(ack=ack, body=body, client=client)

        ack.assert_awaited_once()
        client.views_open.assert_awaited_once()


@pytest.mark.asyncio
class TestRegisterDocHandlers:
    """Tests for handler registration."""

    def test_registers_all_handlers(self):
        """Verify all handlers are registered on the app."""
        app = MagicMock()

        with patch("knowledge_base.config.settings") as mock_settings:
            mock_settings.SLACK_COMMAND_PREFIX = ""
            register_doc_handlers(app)

        # Slash command
        app.command.assert_called_once_with("/create-doc")

        # Shortcut
        app.shortcut.assert_called_once_with("save_as_doc")

        # Modal submissions (3 views)
        assert app.view.call_count == 3
        view_names = [call[0][0] for call in app.view.call_args_list]
        assert "create_doc_modal" in view_names
        assert "thread_to_doc_modal" in view_names
        assert "rejection_reason_modal" in view_names

        # Action handlers (5 regex patterns)
        assert app.action.call_count == 5


@pytest.mark.asyncio
class TestCreateDocSubmit:
    """Tests for create document modal submission."""

    @patch("knowledge_base.slack.doc_creation.init_db", new_callable=AsyncMock)
    @patch("knowledge_base.slack.doc_creation._get_document_creator")
    async def test_manual_mode_creates_document(self, mock_creator_fn, mock_init_db):
        mock_doc = MagicMock()
        mock_doc.doc_id = "DOC001"
        mock_doc.title = "Test Doc"
        mock_doc.status = "draft"
        mock_doc.doc_type = "information"
        mock_doc.area = "engineering"

        mock_creator = MagicMock()
        mock_creator.create_manual = AsyncMock(return_value=mock_doc)
        mock_creator_fn.return_value = mock_creator

        ack = AsyncMock()
        client = AsyncMock()
        body = {"user": {"id": "U123"}}
        view = {
            "state": {
                "values": {
                    "title_block": {"title_input": {"value": "Test Doc"}},
                    "area_block": {"area_select": {"selected_option": {"value": "engineering"}}},
                    "type_block": {"type_select": {"selected_option": {"value": "information"}}},
                    "classification_block": {
                        "classification_select": {"selected_option": {"value": "internal"}}
                    },
                    "mode_block": {"mode_select": {"selected_option": {"value": "manual"}}},
                    "description_block": {"description_input": {"value": "Test content"}},
                }
            }
        }

        await handle_create_doc_submit(ack=ack, body=body, client=client, view=view)

        ack.assert_awaited_once()
        mock_creator.create_manual.assert_awaited_once()
        client.chat_postMessage.assert_awaited_once()

    @patch("knowledge_base.slack.doc_creation.init_db", new_callable=AsyncMock)
    @patch("knowledge_base.slack.doc_creation._get_document_creator")
    async def test_error_sends_failure_message(self, mock_creator_fn, mock_init_db):
        mock_creator = MagicMock()
        mock_creator.create_manual = AsyncMock(side_effect=Exception("DB error"))
        mock_creator_fn.return_value = mock_creator

        ack = AsyncMock()
        client = AsyncMock()
        body = {"user": {"id": "U123"}}
        view = {
            "state": {
                "values": {
                    "title_block": {"title_input": {"value": "Test"}},
                    "area_block": {"area_select": {"selected_option": {"value": "general"}}},
                    "type_block": {"type_select": {"selected_option": {"value": "information"}}},
                    "classification_block": {
                        "classification_select": {"selected_option": {"value": "internal"}}
                    },
                    "mode_block": {"mode_select": {"selected_option": {"value": "manual"}}},
                    "description_block": {"description_input": {"value": "content"}},
                }
            }
        }

        await handle_create_doc_submit(ack=ack, body=body, client=client, view=view)

        ack.assert_awaited_once()
        # Should send error message to user
        client.chat_postMessage.assert_awaited_once()
        call_kwargs = client.chat_postMessage.call_args[1]
        assert "Failed to create document" in call_kwargs["text"]
