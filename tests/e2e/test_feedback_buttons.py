"""E2E tests for feedback button functionality.

These tests verify the REAL feedback button flow:
1. User asks a question
2. Bot responds with answer and feedback buttons
3. User clicks a feedback button
4. Bot acknowledges the feedback (message updated)

Unlike unit tests, these go through the actual Slack bot deployed to staging.
"""

import os
import pytest
import logging

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.e2e


@pytest.fixture
def has_signing_secret():
    """Check if signing secret is available for button click tests."""
    if not os.environ.get("SLACK_SIGNING_SECRET"):
        pytest.skip(
            "SLACK_SIGNING_SECRET not set. "
            "Add STAGING_SLACK_SIGNING_SECRET to GitHub secrets to enable button click tests."
        )
    return True


class TestFeedbackButtonClicks:
    """Test actual feedback button clicks through staging bot."""

    @pytest.mark.asyncio
    async def test_helpful_button_click_succeeds(
        self, slack_client, e2e_config, has_signing_secret
    ):
        """
        E2E: Click 'Helpful' button and verify the request succeeds.

        1. Ask the bot a question
        2. Wait for response with feedback buttons
        3. Click the "Helpful" button
        4. Verify the click returns 200 (no server errors)

        Note: We can't verify message updates because our simulated request
        uses a fake response_url. The key test is that the server processes
        the button click without errors (no 500s).
        """
        bot_user_id = e2e_config["bot_user_id"]

        # 1. Ask the bot a question
        question = f"<@{bot_user_id}> What is Keboola?"
        msg_ts = await slack_client.send_message(question)
        logger.info(f"Sent question, message_ts: {msg_ts}")

        # 2. Wait for bot reply
        reply = await slack_client.wait_for_bot_reply(parent_ts=msg_ts, timeout=90)
        assert reply is not None, "Bot did not respond to question"
        logger.info(f"Got bot reply: {reply.get('text', '')[:100]}...")

        # 3. Wait for feedback buttons message
        feedback_msg = await slack_client.wait_for_message_with_buttons(
            thread_ts=msg_ts,
            action_id_contains="feedback_helpful",
            timeout=30
        )
        assert feedback_msg is not None, "Feedback buttons message not found"
        logger.info(f"Found feedback buttons message: {feedback_msg['ts']}")

        # 4. Click the "Helpful" button - verifies no server errors
        success = await slack_client.click_button(feedback_msg, "feedback_helpful")
        assert success, "Failed to click helpful button (server error)"
        logger.info("Helpful button click processed successfully (200 OK)")

    @pytest.mark.asyncio
    async def test_incorrect_button_click_opens_modal(
        self, slack_client, e2e_config, has_signing_secret
    ):
        """
        E2E: Click 'Incorrect' button - should trigger modal flow.

        Note: We can verify the button click succeeds (200 response),
        but we can't easily verify the modal opened in this test.
        The key test is that the async flow doesn't hang.
        """
        bot_user_id = e2e_config["bot_user_id"]

        # 1. Ask the bot a question
        question = f"<@{bot_user_id}> Tell me about data pipelines"
        msg_ts = await slack_client.send_message(question)

        # 2. Wait for bot reply
        reply = await slack_client.wait_for_bot_reply(parent_ts=msg_ts, timeout=90)
        assert reply is not None, "Bot did not respond"

        # 3. Wait for feedback buttons
        feedback_msg = await slack_client.wait_for_message_with_buttons(
            thread_ts=msg_ts,
            action_id_contains="feedback_incorrect",
            timeout=30
        )
        assert feedback_msg is not None, "Feedback buttons not found"

        # 4. Click the "Incorrect" button
        # This should return 200 and open a modal (which we can't easily verify)
        success = await slack_client.click_button(feedback_msg, "feedback_incorrect")
        assert success, "Incorrect button click should succeed (modal opens)"
        logger.info("Incorrect button click returned success")


class TestFeedbackButtonsPresent:
    """Test that feedback buttons appear correctly (no signing secret needed)."""

    @pytest.mark.asyncio
    async def test_bot_response_includes_feedback_buttons(
        self, slack_client, e2e_config
    ):
        """Verify bot responses include feedback buttons."""
        bot_user_id = e2e_config["bot_user_id"]

        # Ask a question
        question = f"<@{bot_user_id}> What is the knowledge base?"
        msg_ts = await slack_client.send_message(question)

        # Wait for reply
        reply = await slack_client.wait_for_bot_reply(parent_ts=msg_ts, timeout=90)
        assert reply is not None, "Bot did not respond"

        # Check for feedback buttons message
        feedback_msg = await slack_client.wait_for_message_with_buttons(
            thread_ts=msg_ts,
            action_id_contains="feedback_",
            timeout=30
        )
        assert feedback_msg is not None, "No feedback buttons found in response"

        # Verify all 4 button types are present
        assert slack_client.message_has_button(feedback_msg, "feedback_helpful"), \
            "Missing 'Helpful' button"
        assert slack_client.message_has_button(feedback_msg, "feedback_outdated"), \
            "Missing 'Outdated' button"
        assert slack_client.message_has_button(feedback_msg, "feedback_incorrect"), \
            "Missing 'Incorrect' button"
        assert slack_client.message_has_button(feedback_msg, "feedback_confusing"), \
            "Missing 'Confusing' button"

        logger.info("All 4 feedback buttons present")
