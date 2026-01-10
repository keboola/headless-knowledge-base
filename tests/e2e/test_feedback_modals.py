"""End-to-End tests for Enhanced Feedback System with Modals (Phase 10.6)."""

import json
import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch, call
from sqlalchemy import select

from knowledge_base.db.models import (
    Chunk,
    ChunkQuality,
    RawPage,
    UserFeedback,
    GovernanceMetadata,
)
from knowledge_base.slack.bot import _handle_feedback_action, pending_feedback
from knowledge_base.slack.feedback_modals import (
    handle_incorrect_modal_submit,
    handle_outdated_modal_submit,
    handle_confusing_modal_submit,
)
from knowledge_base.slack.modals import (
    build_incorrect_feedback_modal,
    build_outdated_feedback_modal,
    build_confusing_feedback_modal,
)
from knowledge_base.slack.owner_notification import (
    get_owner_email_for_chunks,
    lookup_slack_user_by_email,
    notify_content_owner,
)

# Mark all tests in this module as e2e
pytestmark = pytest.mark.e2e


class TestFeedbackModalBuilders:
    """Tests for modal builder functions."""

    def test_incorrect_modal_structure(self):
        """Verify incorrect feedback modal has correct structure."""
        modal = build_incorrect_feedback_modal(
            message_ts="1234567890.123456",
            chunk_ids=["chunk_1", "chunk_2"],
            channel_id="C123",
            reporter_id="U456",
        )

        assert modal["type"] == "modal"
        assert modal["callback_id"] == "feedback_incorrect_modal"
        assert "Incorrect" in modal["title"]["text"]

        # Verify private_metadata
        metadata = json.loads(modal["private_metadata"])
        assert metadata["message_ts"] == "1234567890.123456"
        assert metadata["chunk_ids"] == ["chunk_1", "chunk_2"]
        assert metadata["channel_id"] == "C123"
        assert metadata["reporter_id"] == "U456"

        # Verify required field (what_incorrect)
        blocks = modal["blocks"]
        block_ids = [b.get("block_id") for b in blocks]
        assert "incorrect_block" in block_ids

    def test_outdated_modal_structure(self):
        """Verify outdated feedback modal has correct structure."""
        modal = build_outdated_feedback_modal(
            message_ts="1234567890.123456",
            chunk_ids=["chunk_1"],
            channel_id="C123",
            reporter_id="U456",
        )

        assert modal["type"] == "modal"
        assert modal["callback_id"] == "feedback_outdated_modal"
        assert "Outdated" in modal["title"]["text"]

        # Verify blocks
        blocks = modal["blocks"]
        block_ids = [b.get("block_id") for b in blocks]
        assert "outdated_block" in block_ids

    def test_confusing_modal_structure(self):
        """Verify confusing feedback modal has correct structure."""
        modal = build_confusing_feedback_modal(
            message_ts="1234567890.123456",
            chunk_ids=["chunk_1"],
            channel_id="C123",
            reporter_id="U456",
        )

        assert modal["type"] == "modal"
        assert modal["callback_id"] == "feedback_confusing_modal"
        assert "Confusing" in modal["title"]["text"]

        # Verify blocks
        blocks = modal["blocks"]
        block_ids = [b.get("block_id") for b in blocks]
        assert "confusion_type_block" in block_ids


class TestNegativeFeedbackOpensModal:
    """Tests that negative feedback opens a modal instead of direct submission."""

    @pytest.mark.asyncio
    async def test_incorrect_feedback_opens_modal(self, test_db_session):
        """Clicking 'Incorrect' should open a modal."""
        chunk_id = f"test_chunk_{uuid.uuid4().hex[:8]}"
        message_ts = "1234567890.123456"
        trigger_id = "trigger_abc123"

        # Setup pending feedback
        pending_feedback[message_ts] = [chunk_id]

        # Mock client
        mock_client = MagicMock()
        mock_client.views_open = MagicMock()

        body = {
            "trigger_id": trigger_id,
            "user": {"id": "U_TEST_USER"},
            "actions": [{"action_id": f"feedback_incorrect_{message_ts}"}],
            "channel": {"id": "C_TEST"},
            "message": {"ts": message_ts},
        }

        with patch("knowledge_base.slack.bot.init_db", new_callable=AsyncMock):
            await _handle_feedback_action(body, mock_client)

        # Verify views_open was called
        mock_client.views_open.assert_called_once()
        call_kwargs = mock_client.views_open.call_args.kwargs
        assert call_kwargs["trigger_id"] == trigger_id
        assert call_kwargs["view"]["callback_id"] == "feedback_incorrect_modal"

    @pytest.mark.asyncio
    async def test_outdated_feedback_opens_modal(self, test_db_session):
        """Clicking 'Outdated' should open a modal."""
        chunk_id = f"test_chunk_{uuid.uuid4().hex[:8]}"
        message_ts = "2234567890.123456"
        trigger_id = "trigger_def456"

        pending_feedback[message_ts] = [chunk_id]

        mock_client = MagicMock()
        mock_client.views_open = MagicMock()

        body = {
            "trigger_id": trigger_id,
            "user": {"id": "U_TEST_USER"},
            "actions": [{"action_id": f"feedback_outdated_{message_ts}"}],
            "channel": {"id": "C_TEST"},
            "message": {"ts": message_ts},
        }

        with patch("knowledge_base.slack.bot.init_db", new_callable=AsyncMock):
            await _handle_feedback_action(body, mock_client)

        mock_client.views_open.assert_called_once()
        call_kwargs = mock_client.views_open.call_args.kwargs
        assert call_kwargs["view"]["callback_id"] == "feedback_outdated_modal"

    @pytest.mark.asyncio
    async def test_confusing_feedback_opens_modal(self, test_db_session):
        """Clicking 'Confusing' should open a modal."""
        chunk_id = f"test_chunk_{uuid.uuid4().hex[:8]}"
        message_ts = "3234567890.123456"
        trigger_id = "trigger_ghi789"

        pending_feedback[message_ts] = [chunk_id]

        mock_client = MagicMock()
        mock_client.views_open = MagicMock()

        body = {
            "trigger_id": trigger_id,
            "user": {"id": "U_TEST_USER"},
            "actions": [{"action_id": f"feedback_confusing_{message_ts}"}],
            "channel": {"id": "C_TEST"},
            "message": {"ts": message_ts},
        }

        with patch("knowledge_base.slack.bot.init_db", new_callable=AsyncMock):
            await _handle_feedback_action(body, mock_client)

        mock_client.views_open.assert_called_once()
        call_kwargs = mock_client.views_open.call_args.kwargs
        assert call_kwargs["view"]["callback_id"] == "feedback_confusing_modal"

    @pytest.mark.asyncio
    async def test_helpful_feedback_does_not_open_modal(self, test_db_session):
        """Clicking 'Helpful' should NOT open a modal - direct submission."""
        chunk_id = f"test_chunk_{uuid.uuid4().hex[:8]}"
        message_ts = "4234567890.123456"

        pending_feedback[message_ts] = [chunk_id]

        mock_client = MagicMock()
        mock_client.views_open = MagicMock()
        mock_client.users_info.return_value = {"ok": True, "user": {"name": "test_user"}}
        mock_client.chat_update = MagicMock()
        mock_client.chat_postEphemeral = MagicMock()

        body = {
            "trigger_id": "trigger_xyz",
            "user": {"id": "U_TEST_USER"},
            "actions": [{"action_id": f"feedback_helpful_{message_ts}"}],
            "channel": {"id": "C_TEST"},
            "message": {"ts": message_ts},
        }

        with patch("knowledge_base.slack.bot.init_db", new_callable=AsyncMock):
            with patch("knowledge_base.slack.bot.submit_feedback", new_callable=AsyncMock):
                await _handle_feedback_action(body, mock_client)

        # views_open should NOT be called for helpful
        mock_client.views_open.assert_not_called()


class TestModalSubmissionHandlers:
    """Tests for modal submission handling."""

    @pytest.mark.asyncio
    async def test_incorrect_modal_saves_feedback_with_correction(self, test_db_session):
        """Submitting incorrect modal should save feedback with suggested correction."""
        chunk_id = f"test_chunk_{uuid.uuid4().hex[:8]}"

        view = {
            "private_metadata": json.dumps({
                "message_ts": "1234567890.123456",
                "chunk_ids": [chunk_id],
                "channel_id": "C_TEST",
                "reporter_id": "U_TEST_USER",
            }),
            "state": {
                "values": {
                    "incorrect_block": {
                        "incorrect_input": {"value": "The date is wrong"}
                    },
                    "correction_block": {
                        "correction_input": {"value": "The correct date is 2024-01-01"}
                    },
                    "evidence_block": {
                        "evidence_select": {
                            "selected_option": {"value": "official_docs", "text": {"text": "Official docs"}}
                        }
                    },
                }
            },
        }

        mock_client = MagicMock()
        mock_client.users_info.return_value = {"ok": True, "user": {"name": "test_user"}}
        mock_client.chat_postEphemeral = MagicMock()

        ack = AsyncMock()
        body = {}

        with patch("knowledge_base.slack.feedback_modals.init_db", new_callable=AsyncMock):
            with patch("knowledge_base.slack.feedback_modals.submit_feedback", new_callable=AsyncMock) as mock_submit:
                with patch("knowledge_base.slack.feedback_modals.notify_content_owner", new_callable=AsyncMock) as mock_notify:
                    with patch("knowledge_base.slack.feedback_modals.confirm_feedback_to_reporter", new_callable=AsyncMock):
                        mock_notify.return_value = True
                        await handle_incorrect_modal_submit(ack, body, mock_client, view)

        # Verify feedback was submitted with correction
        mock_submit.assert_called_once()
        call_kwargs = mock_submit.call_args.kwargs
        assert call_kwargs["chunk_id"] == chunk_id
        assert call_kwargs["feedback_type"] == "incorrect"
        assert "The date is wrong" in call_kwargs["comment"]
        assert call_kwargs["suggested_correction"] == "The correct date is 2024-01-01"

    @pytest.mark.asyncio
    async def test_outdated_modal_saves_feedback(self, test_db_session):
        """Submitting outdated modal should save feedback."""
        chunk_id = f"test_chunk_{uuid.uuid4().hex[:8]}"

        view = {
            "private_metadata": json.dumps({
                "message_ts": "1234567890.123456",
                "chunk_ids": [chunk_id],
                "channel_id": "C_TEST",
                "reporter_id": "U_TEST_USER",
            }),
            "state": {
                "values": {
                    "outdated_block": {
                        "outdated_input": {"value": "The API endpoint changed"}
                    },
                    "current_block": {
                        "current_input": {"value": "New endpoint is /api/v2"}
                    },
                    "when_block": {
                        "when_input": {"value": "Last week"}
                    },
                }
            },
        }

        mock_client = MagicMock()
        mock_client.users_info.return_value = {"ok": True, "user": {"name": "test_user"}}
        mock_client.chat_postEphemeral = MagicMock()

        ack = AsyncMock()
        body = {}

        with patch("knowledge_base.slack.feedback_modals.init_db", new_callable=AsyncMock):
            with patch("knowledge_base.slack.feedback_modals.submit_feedback", new_callable=AsyncMock) as mock_submit:
                with patch("knowledge_base.slack.feedback_modals.notify_content_owner", new_callable=AsyncMock) as mock_notify:
                    with patch("knowledge_base.slack.feedback_modals.confirm_feedback_to_reporter", new_callable=AsyncMock):
                        mock_notify.return_value = True
                        await handle_outdated_modal_submit(ack, body, mock_client, view)

        mock_submit.assert_called_once()
        call_kwargs = mock_submit.call_args.kwargs
        assert call_kwargs["feedback_type"] == "outdated"
        assert "The API endpoint changed" in call_kwargs["comment"]
        assert call_kwargs["suggested_correction"] == "New endpoint is /api/v2"

    @pytest.mark.asyncio
    async def test_confusing_modal_saves_feedback(self, test_db_session):
        """Submitting confusing modal should save feedback."""
        chunk_id = f"test_chunk_{uuid.uuid4().hex[:8]}"

        view = {
            "private_metadata": json.dumps({
                "message_ts": "1234567890.123456",
                "chunk_ids": [chunk_id],
                "channel_id": "C_TEST",
                "reporter_id": "U_TEST_USER",
            }),
            "state": {
                "values": {
                    "confusion_block": {
                        "confusion_select": {
                            "selected_option": {
                                "value": "too_technical",
                                "text": {"text": "Too technical"}
                            }
                        }
                    },
                    "clarification_block": {
                        "clarification_input": {"value": "Please explain in simpler terms"}
                    },
                }
            },
        }

        mock_client = MagicMock()
        mock_client.users_info.return_value = {"ok": True, "user": {"name": "test_user"}}
        mock_client.chat_postEphemeral = MagicMock()

        ack = AsyncMock()
        body = {}

        with patch("knowledge_base.slack.feedback_modals.init_db", new_callable=AsyncMock):
            with patch("knowledge_base.slack.feedback_modals.submit_feedback", new_callable=AsyncMock) as mock_submit:
                with patch("knowledge_base.slack.feedback_modals.notify_content_owner", new_callable=AsyncMock) as mock_notify:
                    with patch("knowledge_base.slack.feedback_modals.confirm_feedback_to_reporter", new_callable=AsyncMock):
                        mock_notify.return_value = False  # Fallback to admin
                        await handle_confusing_modal_submit(ack, body, mock_client, view)

        mock_submit.assert_called_once()
        call_kwargs = mock_submit.call_args.kwargs
        assert call_kwargs["feedback_type"] == "confusing"


class TestOwnerNotification:
    """Tests for content owner notification."""

    @pytest.mark.asyncio
    async def test_get_owner_email_from_governance(self, test_db_session):
        """Should get owner email from ChromaDB metadata (source of truth)."""
        chunk_id = f"chunk_{uuid.uuid4().hex[:8]}"
        owner_email = "owner@example.com"

        # Mock ChromaDB client to return owner in metadata
        mock_chroma = MagicMock()
        mock_chroma.get_metadata = AsyncMock(return_value={
            chunk_id: {"owner": owner_email}
        })

        with patch("knowledge_base.slack.owner_notification.get_chroma_client", return_value=mock_chroma):
            result = await get_owner_email_for_chunks([chunk_id])

        assert result == owner_email
        mock_chroma.get_metadata.assert_called_once_with([chunk_id])

    @pytest.mark.asyncio
    async def test_lookup_slack_user_by_email_success(self):
        """Should find Slack user ID from email."""
        mock_client = MagicMock()
        mock_client.users_lookupByEmail.return_value = {
            "ok": True,
            "user": {"id": "U_OWNER_123"},
        }

        result = await lookup_slack_user_by_email(mock_client, "owner@example.com")

        assert result == "U_OWNER_123"
        mock_client.users_lookupByEmail.assert_called_once_with(email="owner@example.com")

    @pytest.mark.asyncio
    async def test_lookup_slack_user_by_email_not_found(self):
        """Should return None if user not found."""
        from slack_sdk.errors import SlackApiError

        mock_client = MagicMock()
        error_response = MagicMock()
        error_response.get.return_value = "users_not_found"
        mock_client.users_lookupByEmail.side_effect = SlackApiError(
            message="users_not_found",
            response=error_response,
        )

        result = await lookup_slack_user_by_email(mock_client, "unknown@example.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_notify_owner_success_sends_dm(self):
        """Should send DM to owner when found."""
        mock_client = MagicMock()
        mock_client.users_lookupByEmail.return_value = {
            "ok": True,
            "user": {"id": "U_OWNER_123"},
        }
        mock_client.chat_postMessage = MagicMock()

        with patch("knowledge_base.slack.owner_notification.get_owner_email_for_chunks", new_callable=AsyncMock) as mock_get_email:
            with patch("knowledge_base.slack.owner_notification._get_feedback_context", new_callable=AsyncMock) as mock_context:
                mock_get_email.return_value = "owner@example.com"
                mock_context.return_value = {"query": "Test query", "source_titles": ["Doc 1"]}

                result = await notify_content_owner(
                    client=mock_client,
                    chunk_ids=["chunk_1"],
                    feedback_type="incorrect",
                    issue_description="Something is wrong",
                    suggested_correction="Here's the fix",
                    reporter_id="U_REPORTER",
                    channel_id="C_TEST",
                    message_ts="1234567890.123456",
                )

        assert result is True
        mock_client.chat_postMessage.assert_called_once()
        call_kwargs = mock_client.chat_postMessage.call_args.kwargs
        assert call_kwargs["channel"] == "U_OWNER_123"  # DM to owner

    @pytest.mark.asyncio
    async def test_notify_owner_fallback_to_admin_channel(self):
        """Should fall back to admin channel when owner not found."""
        mock_client = MagicMock()
        mock_client.conversations_list.return_value = {
            "channels": [{"name": "knowledge-admins", "id": "C_ADMIN"}]
        }
        mock_client.chat_postMessage = MagicMock()

        with patch("knowledge_base.slack.owner_notification.get_owner_email_for_chunks", new_callable=AsyncMock) as mock_get_email:
            with patch("knowledge_base.slack.owner_notification._get_feedback_context", new_callable=AsyncMock) as mock_context:
                mock_get_email.return_value = None  # No owner
                mock_context.return_value = {"query": "Test query", "source_titles": []}

                result = await notify_content_owner(
                    client=mock_client,
                    chunk_ids=["chunk_1"],
                    feedback_type="outdated",
                    issue_description="Content is old",
                    suggested_correction=None,
                    reporter_id="U_REPORTER",
                    channel_id="C_TEST",
                    message_ts="1234567890.123456",
                )

        assert result is False  # Owner not notified
        mock_client.chat_postMessage.assert_called_once()
        call_kwargs = mock_client.chat_postMessage.call_args.kwargs
        assert call_kwargs["channel"] == "C_ADMIN"  # Admin channel


class TestFullFeedbackModalFlow:
    """Integration tests for complete feedback modal flow."""

    @pytest.mark.asyncio
    async def test_complete_incorrect_feedback_flow(self, test_db_session):
        """
        Full flow:
        1. User clicks Incorrect button
        2. Modal opens
        3. User submits modal with correction
        4. Feedback saved with suggested_correction
        5. Owner notified (or admin channel)
        6. Reporter gets confirmation
        """
        chunk_id = f"test_chunk_{uuid.uuid4().hex[:8]}"
        message_ts = "9999999999.999999"
        trigger_id = "trigger_full_flow"

        # Setup pending feedback
        pending_feedback[message_ts] = [chunk_id]

        # Step 1: Click Incorrect button
        mock_client = MagicMock()
        mock_client.views_open = MagicMock()

        body = {
            "trigger_id": trigger_id,
            "user": {"id": "U_TEST_USER"},
            "actions": [{"action_id": f"feedback_incorrect_{message_ts}"}],
            "channel": {"id": "C_TEST"},
            "message": {"ts": message_ts},
        }

        with patch("knowledge_base.slack.bot.init_db", new_callable=AsyncMock):
            await _handle_feedback_action(body, mock_client)

        # Verify modal was opened
        mock_client.views_open.assert_called_once()
        opened_view = mock_client.views_open.call_args.kwargs["view"]
        assert opened_view["callback_id"] == "feedback_incorrect_modal"

        # Step 2-3: User fills and submits modal
        view = {
            "private_metadata": json.dumps({
                "message_ts": message_ts,
                "chunk_ids": [chunk_id],
                "channel_id": "C_TEST",
                "reporter_id": "U_TEST_USER",
            }),
            "state": {
                "values": {
                    "incorrect_block": {
                        "incorrect_input": {"value": "The API returns wrong format"}
                    },
                    "correction_block": {
                        "correction_input": {"value": "It should return JSON, not XML"}
                    },
                    "evidence_block": {
                        "evidence_select": {
                            "selected_option": {"value": "tested_myself", "text": {"text": "Tested myself"}}
                        }
                    },
                }
            },
        }

        # Reset client mocks for modal submission
        mock_client.users_info.return_value = {"ok": True, "user": {"name": "test_user"}}
        mock_client.chat_postEphemeral = MagicMock()
        mock_client.chat_postMessage = MagicMock()

        saved_feedback = []

        async def capture_feedback(**kwargs):
            saved_feedback.append(kwargs)
            return MagicMock()

        ack = AsyncMock()
        modal_body = {}

        with patch("knowledge_base.slack.feedback_modals.init_db", new_callable=AsyncMock):
            with patch("knowledge_base.slack.feedback_modals.submit_feedback", side_effect=capture_feedback):
                with patch("knowledge_base.slack.feedback_modals.notify_content_owner", new_callable=AsyncMock) as mock_notify:
                    with patch("knowledge_base.slack.feedback_modals.confirm_feedback_to_reporter", new_callable=AsyncMock) as mock_confirm:
                        mock_notify.return_value = True
                        await handle_incorrect_modal_submit(ack, modal_body, mock_client, view)

        # Verify feedback was saved with correction details
        assert len(saved_feedback) == 1
        fb = saved_feedback[0]
        assert fb["chunk_id"] == chunk_id
        assert fb["feedback_type"] == "incorrect"
        assert "The API returns wrong format" in fb["comment"]
        assert fb["suggested_correction"] == "It should return JSON, not XML"

        # Verify owner was notified
        mock_notify.assert_called_once()

        # Verify reporter got confirmation
        mock_confirm.assert_called_once()
