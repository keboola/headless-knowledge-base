"""Fixtures for End-to-End tests."""

import os
import pytest
import asyncio
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from knowledge_base.config import settings


@pytest.fixture(scope="session")
def chromadb_available():
    """Check if Graphiti is available and skip tests if not.

    This fixture attempts to connect to Graphiti and skips the test
    if the connection fails.

    Note: This is still named chromadb_available for backward compatibility
    but now checks Graphiti.

    IMPORTANT: Tests that require this fixture need:
    1. GRAPH_ENABLE_GRAPHITI=true
    2. ANTHROPIC_API_KEY set (for entity extraction)
    3. Network access to Neo4j (not possible from GitHub Actions to VPC internal IPs)
    """
    from knowledge_base.config import settings

    if not settings.GRAPH_ENABLE_GRAPHITI:
        pytest.skip("Graphiti is disabled in settings.")

    # Check for Anthropic API key (required for entity extraction)
    if not os.environ.get("ANTHROPIC_API_KEY") and not settings.ANTHROPIC_API_KEY:
        pytest.skip(
            "ANTHROPIC_API_KEY not available. "
            "Graphiti requires this for entity extraction."
        )

    # Check for Neo4j connection by actually trying to create a client
    try:
        from knowledge_base.graph.graphiti_client import GraphitiClient, GraphitiClientError

        # Create a new client instance (don't use singleton to avoid polluting other tests)
        client = GraphitiClient()

        # Try to actually connect using the session event loop
        # IMPORTANT: Do NOT create a new event loop here — it conflicts with
        # pytest-asyncio's session loop and causes "Future attached to a different loop"
        # errors in downstream async tests.
        import asyncio
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        try:
            # Use a short timeout to fail fast if Neo4j is not reachable
            async def test_connection():
                try:
                    graphiti = await asyncio.wait_for(client.get_client(), timeout=10.0)
                    return True
                except asyncio.TimeoutError:
                    raise GraphitiClientError("Connection to Neo4j timed out")
                except Exception as e:
                    raise GraphitiClientError(f"Failed to connect: {e}")
                finally:
                    # Clean up
                    GraphitiClient.reset()

            loop.run_until_complete(test_connection())
        finally:
            # Do NOT close the loop — it's shared with the test session
            pass

        return True

    except Exception as e:
        pytest.skip(
            f"Graphiti/Neo4j not reachable: {e}. "
            "These tests require network access to the staging Neo4j VM. "
            "When running from GitHub Actions, the runner cannot reach VPC internal IPs. "
            "Run these tests from within GCP VPC or with a local Neo4j instance."
        )

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session")
def e2e_config():
    """Load E2E configuration from environment variables."""
    config = {
        "bot_token": os.environ.get("SLACK_BOT_TOKEN"),
        "user_token": os.environ.get("SLACK_USER_TOKEN"),
        "channel_id": os.environ.get("E2E_TEST_CHANNEL_ID"),
        "bot_user_id": os.environ.get("E2E_BOT_USER_ID"),
        "db_url": settings.DATABASE_URL,
    }
    
    missing = [k for k, v in config.items() if not v]
    if missing:
        pytest.skip(f"Skipping E2E tests. Missing config: {', '.join(missing)}")
        
    return config

@pytest.fixture(scope="session")
async def db_session(e2e_config) -> AsyncGenerator[AsyncSession, None]:
    """Provide a database session connected to the real DB."""
    from knowledge_base.db.models import Base
    engine = create_async_engine(e2e_config["db_url"], echo=False)
    
    # Create tables if they don't exist (important for local temp DB)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    
    async with async_session() as session:
        yield session
        
    await engine.dispose()

@pytest.fixture(scope="session")
def slack_client(e2e_config):
    """Provide the SlackTestClient."""
    from tests.e2e.slack_client import SlackTestClient
    return SlackTestClient(e2e_config)


@pytest.fixture(scope="function")
async def test_db_session():
    """Provide an in-memory database session for isolated tests.

    This is for tests that don't need the real e2e database.
    """
    from knowledge_base.db.models import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with async_session() as session:
        yield session

    await engine.dispose()


# ============================================================================
# Admin Escalation Test Fixtures
# ============================================================================

@pytest.fixture(scope="session")
def admin_channel_id(slack_client):
    """Get the admin channel ID from env or skip test.

    E2E_ADMIN_CHANNEL can be either:
    - A channel ID (starts with 'C', e.g., 'C0A6WU7EFMY')
    - A channel name (e.g., 'knowledge-admins')

    The bot must be a member of this channel for tests to work.
    """
    channel_value = os.environ.get("E2E_ADMIN_CHANNEL")
    if not channel_value:
        pytest.skip(
            "E2E_ADMIN_CHANNEL not set. Set this to either a channel ID "
            "(e.g., C0A6WU7EFMY) or channel name (e.g., knowledge-admins)."
        )

    # If it looks like a channel ID (starts with C), use it directly
    if channel_value.startswith("C"):
        channel_id = channel_value
    else:
        # Otherwise, look it up by name
        channel_id = slack_client.find_channel_by_name(channel_value)
        if not channel_id:
            pytest.skip(
                f"Admin channel '#{channel_value}' not found. "
                "Create the channel and add the bot as a member."
            )

    # Verify bot is a member of the channel by trying to read history
    try:
        slack_client.bot_client.conversations_history(
            channel=channel_id,
            limit=1
        )
    except Exception as e:
        if "not_in_channel" in str(e):
            pytest.skip(
                f"Bot is not a member of admin channel {channel_id}. "
                "Please add the bot to the channel: "
                "1. Open the channel in Slack "
                "2. Click the channel name at the top "
                "3. Go to 'Integrations' tab "
                "4. Click 'Add apps' and add the bot"
            )
        raise

    return channel_id


@pytest.fixture(scope="session")
def test_owner_email():
    """Email of a test user for owner notification tests.

    Set E2E_TEST_OWNER_EMAIL to a real user's email in the test workspace.
    """
    email = os.environ.get("E2E_TEST_OWNER_EMAIL")
    if not email:
        pytest.skip(
            "E2E_TEST_OWNER_EMAIL not set. Set this to a real user's email "
            "in the test Slack workspace for owner notification tests."
        )
    return email


@pytest.fixture(scope="session")
def test_owner_user(slack_client, test_owner_email):
    """Get the Slack user info for the test owner.

    Returns dict with 'id', 'name', 'email' etc.
    """
    user = slack_client.lookup_user_by_email(test_owner_email)
    if not user:
        pytest.skip(
            f"Test owner with email '{test_owner_email}' not found in Slack. "
            "Ensure the email matches a real user in the test workspace."
        )
    return user


@pytest.fixture(scope="function")
def test_start_timestamp(slack_client):
    """Get a timestamp at the start of each test for filtering messages.

    Use this to only check messages sent AFTER the test started.
    """
    return slack_client.get_current_timestamp()


@pytest.fixture(scope="function")
def unique_test_id():
    """Generate a unique ID for each test to avoid collisions."""
    import uuid
    return uuid.uuid4().hex[:8]
