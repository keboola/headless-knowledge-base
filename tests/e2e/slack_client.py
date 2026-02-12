"""Slack Client helper for E2E tests."""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any, List, Optional

import httpx
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

logger = logging.getLogger(__name__)


class SlackTestClient:
    """Helper client for interacting with Slack in E2E tests."""

    def __init__(self, config: dict):
        self.bot_token = config["bot_token"]
        self.user_token = config["user_token"]
        self.channel_id = config["channel_id"]
        self.bot_user_id = config["bot_user_id"]
        
        # We use two clients: one acting as the bot (checking stuff), 
        # one acting as a user (triggering stuff).
        # Actually, for E2E tests, we usually want to act as a *user* interacting with the bot.
        self.user_client = WebClient(token=self.user_token)
        self.bot_client = WebClient(token=self.bot_token)

    async def send_message(self, text: str, thread_ts: Optional[str] = None) -> str:
        """Send a message to the test channel as a user."""
        try:
            response = self.user_client.chat_postMessage(
                channel=self.channel_id,
                text=text,
                thread_ts=thread_ts
            )
            return response["ts"]
        except SlackApiError as e:
            logger.error(f"Error sending message: {e}")
            raise

    async def add_reaction(self, name: str, timestamp: str) -> None:
        """Add an emoji reaction to a message as a user."""
        try:
            self.user_client.reactions_add(
                channel=self.channel_id,
                name=name,
                timestamp=timestamp
            )
        except SlackApiError as e:
            # Ignore if already added
            if e.response["error"] != "already_reacted":
                logger.error(f"Error adding reaction: {e}")
                raise

    # Status messages the bot posts before the real answer
    STATUS_MESSAGES = {"Searching the knowledge base...", "Thinking..."}

    # Feedback prompt prefixes (posted as separate messages, not the answer)
    FEEDBACK_PREFIXES = ("was this helpful", "thanks!", "thanks for your feedback")

    def _is_bot_message(self, msg: dict) -> bool:
        """Check if a message is from the bot (by user ID or bot_id)."""
        if msg.get("user") == self.bot_user_id:
            return True
        # Fallback: some bot messages use bot_id instead of user
        if msg.get("bot_id") and not msg.get("user"):
            return True
        return False

    def _is_substantive_bot_message(self, text: str) -> bool:
        """Check if a bot message text is a real answer (not status/feedback)."""
        if text in self.STATUS_MESSAGES:
            return False
        text_lower = text.strip().lower()
        for prefix in self.FEEDBACK_PREFIXES:
            if text_lower.startswith(prefix):
                return False
        # Very short messages are UI elements (feedback buttons, etc.)
        if len(text) < 20:
            return False
        return True

    async def wait_for_bot_reply(
        self,
        parent_ts: Optional[str] = None,
        after_ts: Optional[str] = None,
        timeout: int = 90
    ) -> Optional[dict]:
        """Wait for the bot to post a substantive message in the channel or thread.

        Handles the bot's message flow:
        1. Bot posts "Thinking..." status message
        2. Bot edits "Thinking..." to the real answer
        3. Bot posts "Was this helpful?" feedback buttons (separate message)

        This method waits for step 2 (the edited real answer) and returns it.
        Skips status messages, feedback prompts, and other short UI messages.
        """
        start_time = time.time()
        poll_count = 0

        while time.time() - start_time < timeout:
            try:
                if parent_ts:
                    # Check thread replies
                    history = self.user_client.conversations_replies(
                        channel=self.channel_id,
                        ts=parent_ts
                    )
                    messages = history["messages"]
                else:
                    # Check channel history
                    history = self.user_client.conversations_history(
                        channel=self.channel_id,
                        oldest=after_ts or 0
                    )
                    messages = history["messages"]

                # Look for substantive bot message
                for msg in messages:
                    if not self._is_bot_message(msg):
                        continue
                    if after_ts and float(msg["ts"]) <= float(after_ts):
                        continue

                    text = msg.get("text", "")
                    if self._is_substantive_bot_message(text):
                        logger.debug(
                            f"Found bot reply after {poll_count} polls "
                            f"({time.time() - start_time:.1f}s): {text[:80]}..."
                        )
                        return msg

                if poll_count % 10 == 0 and poll_count > 0:
                    bot_texts = [
                        m.get("text", "")[:50]
                        for m in messages
                        if self._is_bot_message(m)
                    ]
                    logger.debug(
                        f"Poll {poll_count} ({time.time() - start_time:.0f}s): "
                        f"bot messages={bot_texts}"
                    )

            except SlackApiError as e:
                logger.warning(f"Error polling Slack: {e}")

            poll_count += 1
            await asyncio.sleep(2)

        logger.warning(
            f"Timed out after {timeout}s waiting for bot reply "
            f"(parent_ts={parent_ts}, after_ts={after_ts})"
        )
        return None

    # Phrases that indicate the bot failed to find real information
    NO_INFO_PHRASES = [
        "couldn't find relevant",
        "don't have any information",
        "no relevant information",
        "unable to find",
        "no results found",
        "i don't have enough",
        "i couldn't find any",
    ]

    @staticmethod
    def assert_substantive_response(reply: dict, min_length: int = 100) -> str:
        """Assert that a bot reply contains a substantive, useful answer.

        Fails if the response is a "no information" fallback or too short.

        Args:
            reply: The bot reply message dict
            min_length: Minimum expected response length for a real answer

        Returns:
            The response text (for further assertions if needed)
        """
        assert reply is not None, "Bot did not respond at all"
        text = reply.get("text", "")

        # Check for "no information" fallback responses
        text_lower = text.lower()
        for phrase in SlackTestClient.NO_INFO_PHRASES:
            assert phrase not in text_lower, (
                f"Bot returned a 'no information' fallback instead of a real answer: "
                f"{text[:200]}..."
            )

        # Check minimum length - a real answer should be substantive
        assert len(text) >= min_length, (
            f"Bot response too short ({len(text)} chars, expected >= {min_length}). "
            f"Response: {text[:200]}..."
        )

        return text

    def get_messages(self, limit: int = 10) -> List[dict]:
        """Get recent messages from the channel."""
        try:
            result = self.bot_client.conversations_history(
                channel=self.channel_id,
                limit=limit
            )
            return result["messages"]
        except SlackApiError as e:
            logger.error(f"Error getting history: {e}")
            return []

    def find_channel_by_name(self, channel_name: str) -> Optional[str]:
        """Find a channel ID by name (without #).

        Args:
            channel_name: Channel name without # prefix (e.g., 'knowledge-admins')

        Returns:
            Channel ID if found, None otherwise
        """
        try:
            # Search public channels
            result = self.bot_client.conversations_list(
                types="public_channel,private_channel",
                limit=200
            )
            for channel in result.get("channels", []):
                if channel["name"] == channel_name:
                    return channel["id"]
            return None
        except SlackApiError as e:
            logger.error(f"Error finding channel {channel_name}: {e}")
            return None

    def get_channel_messages_by_name(
        self,
        channel_name: str,
        limit: int = 10,
        oldest: Optional[str] = None
    ) -> List[dict]:
        """Get recent messages from a channel by name.

        Args:
            channel_name: Channel name without # prefix
            limit: Max messages to return
            oldest: Only return messages after this timestamp

        Returns:
            List of messages, empty if channel not found
        """
        channel_id = self.find_channel_by_name(channel_name)
        if not channel_id:
            logger.warning(f"Channel '{channel_name}' not found")
            return []

        try:
            kwargs = {"channel": channel_id, "limit": limit}
            if oldest:
                kwargs["oldest"] = oldest
            result = self.bot_client.conversations_history(**kwargs)
            return result.get("messages", [])
        except SlackApiError as e:
            logger.error(f"Error getting messages from {channel_name}: {e}")
            return []

    async def wait_for_message_in_channel(
        self,
        channel_name: str,
        contains: Optional[str] = None,
        from_bot: bool = True,
        timeout: int = 30,
        oldest: Optional[str] = None
    ) -> Optional[dict]:
        """Wait for a message to appear in a specific channel.

        Args:
            channel_name: Channel name without # prefix
            contains: Optional text the message should contain
            from_bot: If True, only match messages from the bot
            timeout: Max seconds to wait
            oldest: Only check messages after this timestamp

        Returns:
            The matching message dict, or None if timeout
        """
        channel_id = self.find_channel_by_name(channel_name)
        if not channel_id:
            logger.error(f"Channel '{channel_name}' not found")
            return None

        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                kwargs = {"channel": channel_id, "limit": 20}
                if oldest:
                    kwargs["oldest"] = oldest
                result = self.bot_client.conversations_history(**kwargs)

                for msg in result.get("messages", []):
                    # Filter by sender if needed
                    if from_bot and msg.get("user") != self.bot_user_id:
                        continue

                    # Filter by content if needed
                    text = msg.get("text", "")
                    blocks_text = self._extract_text_from_blocks(msg.get("blocks", []))
                    full_text = f"{text} {blocks_text}"

                    if contains and contains.lower() not in full_text.lower():
                        continue

                    return msg

            except SlackApiError as e:
                logger.warning(f"Error polling channel {channel_name}: {e}")

            await asyncio.sleep(1)

        return None

    def _extract_text_from_blocks(self, blocks: List[dict]) -> str:
        """Extract text content from Slack blocks for searching."""
        texts = []
        for block in blocks:
            if block.get("type") == "section":
                text_obj = block.get("text", {})
                if text_obj.get("text"):
                    texts.append(text_obj["text"])
                # Check fields in section
                for field in block.get("fields", []):
                    if field.get("text"):
                        texts.append(field["text"])
            elif block.get("type") == "header":
                text_obj = block.get("text", {})
                if text_obj.get("text"):
                    texts.append(text_obj["text"])
            elif block.get("type") == "context":
                for element in block.get("elements", []):
                    if element.get("text"):
                        texts.append(element["text"])
        return " ".join(texts)

    async def get_dm_with_user(self, user_id: str) -> Optional[str]:
        """Open or get existing DM channel with a user.

        Args:
            user_id: The user's Slack ID

        Returns:
            DM channel ID if successful, None otherwise
        """
        try:
            result = self.bot_client.conversations_open(users=[user_id])
            return result["channel"]["id"]
        except SlackApiError as e:
            logger.error(f"Error opening DM with {user_id}: {e}")
            return None

    async def get_dm_messages(
        self,
        user_id: str,
        limit: int = 10,
        oldest: Optional[str] = None
    ) -> List[dict]:
        """Get recent DMs with a specific user.

        Args:
            user_id: The user's Slack ID
            limit: Max messages to return
            oldest: Only return messages after this timestamp

        Returns:
            List of DM messages
        """
        dm_channel = await self.get_dm_with_user(user_id)
        if not dm_channel:
            return []

        try:
            kwargs = {"channel": dm_channel, "limit": limit}
            if oldest:
                kwargs["oldest"] = oldest
            result = self.bot_client.conversations_history(**kwargs)
            return result.get("messages", [])
        except SlackApiError as e:
            logger.error(f"Error getting DMs with {user_id}: {e}")
            return []

    async def wait_for_dm(
        self,
        user_id: str,
        contains: Optional[str] = None,
        timeout: int = 30,
        oldest: Optional[str] = None
    ) -> Optional[dict]:
        """Wait for a DM to be sent to a user.

        Args:
            user_id: The user's Slack ID to check DMs for
            contains: Optional text the message should contain
            timeout: Max seconds to wait
            oldest: Only check messages after this timestamp

        Returns:
            The matching message dict, or None if timeout
        """
        dm_channel = await self.get_dm_with_user(user_id)
        if not dm_channel:
            return None

        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                kwargs = {"channel": dm_channel, "limit": 20}
                if oldest:
                    kwargs["oldest"] = oldest
                result = self.bot_client.conversations_history(**kwargs)

                for msg in result.get("messages", []):
                    # Only check bot messages
                    if msg.get("user") != self.bot_user_id:
                        continue

                    text = msg.get("text", "")
                    blocks_text = self._extract_text_from_blocks(msg.get("blocks", []))
                    full_text = f"{text} {blocks_text}"

                    if contains and contains.lower() not in full_text.lower():
                        continue

                    return msg

            except SlackApiError as e:
                logger.warning(f"Error polling DM with {user_id}: {e}")

            await asyncio.sleep(1)

        return None

    def lookup_user_by_email(self, email: str) -> Optional[dict]:
        """Look up a Slack user by email.

        Args:
            email: User's email address

        Returns:
            User info dict if found, None otherwise
        """
        try:
            result = self.bot_client.users_lookupByEmail(email=email)
            return result.get("user")
        except SlackApiError as e:
            if e.response.get("error") == "users_not_found":
                return None
            logger.error(f"Error looking up user by email {email}: {e}")
            return None

    def message_has_button(self, message: dict, action_id_contains: str) -> bool:
        """Check if a message contains a button with specific action_id.

        Args:
            message: Slack message dict
            action_id_contains: Substring to look for in action_id

        Returns:
            True if button found
        """
        for block in message.get("blocks", []):
            if block.get("type") == "actions":
                for element in block.get("elements", []):
                    action_id = element.get("action_id", "")
                    if action_id_contains in action_id:
                        return True
        return False

    def get_current_timestamp(self) -> str:
        """Get current time as Slack timestamp string for filtering."""
        return str(time.time())

    def _find_button_in_message(
        self, message: dict, action_id_prefix: str
    ) -> Optional[dict]:
        """Find a button element in a message by action_id prefix.

        Args:
            message: Slack message dict with blocks
            action_id_prefix: Prefix to match (e.g., "feedback_helpful")

        Returns:
            Button element dict if found, None otherwise
        """
        for block in message.get("blocks", []):
            if block.get("type") == "actions":
                for element in block.get("elements", []):
                    action_id = element.get("action_id", "")
                    if action_id.startswith(action_id_prefix):
                        return element
        return None

    def _sign_slack_request(self, body: str, timestamp: str) -> str:
        """Sign a request body using Slack signing secret.

        Args:
            body: Request body as string
            timestamp: Unix timestamp as string

        Returns:
            Signature in format "v0=<hex>"
        """
        signing_secret = (
            os.environ.get("SLACK_STAGING_SIGNING_SECRET")
            or os.environ.get("SLACK_SIGNING_SECRET", "")
        )
        if not signing_secret:
            raise ValueError(
                "SLACK_STAGING_SIGNING_SECRET or SLACK_SIGNING_SECRET not set. "
                "Fetch from Secret Manager: gcloud secrets versions access latest "
                "--secret=slack-signing-secret-staging --project=ai-knowledge-base-42"
            )

        sig_basestring = f"v0:{timestamp}:{body}"
        signature = hmac.new(
            signing_secret.encode(),
            sig_basestring.encode(),
            hashlib.sha256
        ).hexdigest()
        return f"v0={signature}"

    async def click_button(
        self,
        message: dict,
        action_id_prefix: str,
        user_id: Optional[str] = None
    ) -> bool:
        """Click a button in a message by posting to the staging bot endpoint.

        This simulates what Slack does when a user clicks a button:
        it sends a signed POST request to the bot's /slack/events endpoint.

        Args:
            message: The message dict containing the button
            action_id_prefix: e.g., "feedback_helpful" to find "feedback_helpful_123.456"
            user_id: User ID to simulate (defaults to test user)

        Returns:
            True if click succeeded, False otherwise

        Requires:
            - SLACK_SIGNING_SECRET env var
            - STAGING_BOT_URL env var (or defaults to staging URL)
        """
        # Find the button
        button = self._find_button_in_message(message, action_id_prefix)
        if not button:
            logger.error(f"Button with prefix '{action_id_prefix}' not found in message")
            return False

        action_id = button.get("action_id", "")
        logger.info(f"Clicking button with action_id: {action_id}")

        # Build the action payload (simulating what Slack sends)
        timestamp = str(int(time.time()))
        payload = {
            "type": "block_actions",
            "user": {
                "id": user_id or "U_E2E_TEST_USER",
                "username": "e2e_test_user",
                "name": "E2E Test User",
                "team_id": "T_E2E_STAGING",
            },
            "team": {
                "id": "T_E2E_STAGING",
                "domain": "e2e-staging",
            },
            "channel": {
                "id": self.channel_id,
                "name": "e2e-test-channel",
            },
            "message": message,
            "actions": [
                {
                    "action_id": action_id,
                    "block_id": button.get("block_id", ""),
                    "type": "button",
                    "action_ts": timestamp,
                }
            ],
            "trigger_id": f"{timestamp}.{self.channel_id}",
            "response_url": "https://hooks.slack.com/actions/FAKE/FAKE/FAKE",
            "api_app_id": "A_E2E_TEST_APP",
            "token": "",
        }

        body = f"payload={json.dumps(payload)}"

        # Sign the request
        try:
            signature = self._sign_slack_request(body, timestamp)
        except ValueError as e:
            logger.error(f"Cannot sign request: {e}")
            return False

        # Get staging bot URL
        staging_url = os.environ.get(
            "STAGING_BOT_URL",
            "https://slack-bot-staging-4aosg235qq-uc.a.run.app"
        )
        endpoint = f"{staging_url}/slack/events"

        # POST to the staging endpoint
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Slack-Request-Timestamp": timestamp,
            "X-Slack-Signature": signature,
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    endpoint,
                    content=body,
                    headers=headers,
                    timeout=30.0
                )

            if response.status_code == 200:
                logger.info(f"Button click succeeded: {response.status_code}")
                return True
            else:
                logger.error(
                    f"Button click failed: {response.status_code} - {response.text}"
                )
                return False

        except Exception as e:
            logger.error(f"Button click request failed: {e}")
            return False

    async def wait_for_message_with_buttons(
        self,
        thread_ts: str,
        action_id_contains: str,
        timeout: int = 30
    ) -> Optional[dict]:
        """Wait for a message in a thread that contains specific buttons.

        Args:
            thread_ts: Thread timestamp to search in
            action_id_contains: Substring to look for in button action_ids
            timeout: Max seconds to wait

        Returns:
            Message dict if found, None if timeout
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                # Get thread messages
                history = self.bot_client.conversations_replies(
                    channel=self.channel_id,
                    ts=thread_ts
                )

                for msg in history.get("messages", []):
                    if self.message_has_button(msg, action_id_contains):
                        return msg

            except SlackApiError as e:
                logger.warning(f"Error getting thread: {e}")

            await asyncio.sleep(1)

        return None

    async def wait_for_message_update(
        self,
        message_ts: str,
        contains: str,
        timeout: int = 30
    ) -> Optional[dict]:
        """Wait for a message to be updated to contain specific text.

        Args:
            message_ts: Timestamp of the message to watch
            contains: Text the updated message should contain
            timeout: Max seconds to wait

        Returns:
            Updated message dict if found, None if timeout
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                # Get the specific message
                history = self.bot_client.conversations_history(
                    channel=self.channel_id,
                    latest=message_ts,
                    oldest=message_ts,
                    inclusive=True,
                    limit=1
                )

                messages = history.get("messages", [])
                if messages:
                    msg = messages[0]
                    text = msg.get("text", "")
                    blocks_text = self._extract_text_from_blocks(msg.get("blocks", []))
                    full_text = f"{text} {blocks_text}"

                    if contains.lower() in full_text.lower():
                        return msg

            except SlackApiError as e:
                logger.warning(f"Error checking message update: {e}")

            await asyncio.sleep(1)

        return None
