"""Fixtures for integration tests with real database."""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from knowledge_base.db.models import Base, Document, AreaApprover, DocumentVersion
from knowledge_base.documents.models import DocumentArea


@pytest.fixture(scope="function")
def test_db_engine():
    """Create an in-memory SQLite engine for testing.

    Each test gets a fresh database for complete isolation.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    return engine


@pytest_asyncio.fixture(scope="function")
async def test_db_session(test_db_engine):
    """Create tables and provide a test session.

    Each test gets a fresh database with all tables created.
    Tables are dropped after the test completes.
    """
    async with test_db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session_factory = async_sessionmaker(
        test_db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session_factory() as session:
        yield session

    # Cleanup: drop all tables
    async with test_db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await test_db_engine.dispose()


@pytest.fixture
def test_users():
    """Provide test user IDs representing different roles."""
    return {
        "author": "U_AUTHOR_001",
        "approver_1": "U_APPROVER_001",
        "approver_2": "U_APPROVER_002",
        "approver_3": "U_APPROVER_003",
        "random_user": "U_RANDOM_001",
    }


@pytest.fixture
def mock_llm():
    """Create a mock LLM that returns predictable content.

    The LLM interface requires an async `generate` method.
    """
    llm = MagicMock()

    async def generate_content(prompt: str) -> str:
        # Return appropriate content based on prompt type
        if "policy" in prompt.lower():
            return """## Purpose
This policy establishes guidelines for operations.

## Scope
Applies to all employees.

## Policy Statement
All employees must follow these procedures.

---
### Suggestions
- Consider adding examples
- May need legal review"""
        elif "thread" in prompt.lower() or "conversation" in prompt.lower():
            return """# Thread Summary Document

## Summary
Key information from the discussion.

## Action Items
- Item 1
- Item 2

---
### Suggestions
- Add more context about decisions made"""
        elif "improve" in prompt.lower() or "feedback" in prompt.lower():
            return """## Purpose
This policy establishes comprehensive guidelines for operations.

## Scope
Applies to all employees and contractors.

## Policy Statement
All employees must follow these procedures with the following additions based on feedback.

## Safety Precautions
Added section addressing safety concerns.

## Rollback Procedures
Added rollback steps as requested."""
        else:
            return """## Generated Content

This is AI-generated content for testing.

---
### Suggestions
- Review for accuracy"""

    llm.generate = AsyncMock(side_effect=generate_content)
    return llm


@pytest.fixture
def mock_slack_client():
    """Create a mock Slack client that tracks notifications.

    Tracks all sent messages for verification in tests.
    """
    slack = MagicMock()
    slack.sent_messages = []

    def track_message(**kwargs):
        slack.sent_messages.append({
            "channel": kwargs.get("channel"),
            "text": kwargs.get("text", ""),
            "blocks": kwargs.get("blocks"),
        })
        return {"ok": True, "ts": "1234567890.123456"}

    slack.chat_postMessage = MagicMock(side_effect=track_message)
    return slack


@pytest_asyncio.fixture
async def configured_approvers(test_db_session, test_users):
    """Pre-configure approvers for test areas.

    Sets up:
    - ENGINEERING: 2 approvers (for multi-approver tests)
    - FINANCE: 1 approver
    - PEOPLE: 1 approver
    - GENERAL: no approvers (for edge case testing)
    """
    from datetime import datetime

    approvers_config = [
        (DocumentArea.ENGINEERING.value, test_users["approver_1"], "Approver One"),
        (DocumentArea.ENGINEERING.value, test_users["approver_2"], "Approver Two"),
        (DocumentArea.FINANCE.value, test_users["approver_1"], "Approver One"),
        (DocumentArea.PEOPLE.value, test_users["approver_3"], "Approver Three"),
    ]

    for area, approver_id, approver_name in approvers_config:
        approver = AreaApprover(
            area=area,
            approver_slack_id=approver_id,
            approver_name=approver_name,
            is_active=True,
            added_by="U_ADMIN",
            added_at=datetime.utcnow(),
        )
        test_db_session.add(approver)

    await test_db_session.commit()
    return approvers_config


@pytest_asyncio.fixture
async def document_creator(test_db_session, mock_llm, mock_slack_client):
    """Create a DocumentCreator with real DB, mock LLM and Slack.

    This fixture provides:
    - Real database operations (in-memory SQLite)
    - Mocked LLM for predictable AI responses
    - Mocked Slack client for notification verification
    """
    from knowledge_base.documents.creator import DocumentCreator
    from knowledge_base.documents.approval import ApprovalConfig

    # Create a sync session wrapper for DocumentCreator
    # DocumentCreator expects a sync Session, but our test uses AsyncSession
    # We need to create a sync session for this

    # Actually, looking at creator.py, it uses sync Session operations
    # We need to adapt our approach

    # For integration tests, let's create a sync engine and session
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    sync_engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(sync_engine)
    SyncSession = sessionmaker(bind=sync_engine)
    sync_session = SyncSession()

    config = ApprovalConfig(
        require_all_approvers=False,
        auto_approve_updates=False,
        expiry_days=14,
    )

    creator = DocumentCreator(
        session=sync_session,
        llm=mock_llm,
        approval_config=config,
        slack_client=mock_slack_client,
    )

    yield creator

    sync_session.close()
    sync_engine.dispose()


@pytest_asyncio.fixture
async def sync_session_with_approvers(test_users):
    """Create a sync session with pre-configured approvers.

    This is needed because DocumentCreator uses sync SQLAlchemy Session.
    """
    from datetime import datetime
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    sync_engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(sync_engine)
    SyncSession = sessionmaker(bind=sync_engine)
    session = SyncSession()

    # Add approvers
    approvers_config = [
        (DocumentArea.ENGINEERING.value, test_users["approver_1"], "Approver One"),
        (DocumentArea.ENGINEERING.value, test_users["approver_2"], "Approver Two"),
        (DocumentArea.FINANCE.value, test_users["approver_1"], "Approver One"),
        (DocumentArea.PEOPLE.value, test_users["approver_3"], "Approver Three"),
    ]

    for area, approver_id, approver_name in approvers_config:
        approver = AreaApprover(
            area=area,
            approver_slack_id=approver_id,
            approver_name=approver_name,
            is_active=True,
            added_by="U_ADMIN",
            added_at=datetime.utcnow(),
        )
        session.add(approver)

    session.commit()

    yield session

    session.close()
    sync_engine.dispose()


@pytest_asyncio.fixture
async def creator_with_approvers(sync_session_with_approvers, mock_llm, mock_slack_client):
    """Create a DocumentCreator with pre-configured approvers."""
    from knowledge_base.documents.creator import DocumentCreator
    from knowledge_base.documents.approval import ApprovalConfig

    config = ApprovalConfig(
        require_all_approvers=False,
        auto_approve_updates=False,
        expiry_days=14,
    )

    creator = DocumentCreator(
        session=sync_session_with_approvers,
        llm=mock_llm,
        approval_config=config,
        slack_client=mock_slack_client,
    )

    return creator
