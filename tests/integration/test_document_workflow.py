"""Integration tests for document creation workflow with real database."""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import select, create_engine
from sqlalchemy.orm import sessionmaker

from knowledge_base.db.models import Base, Document, AreaApprover, DocumentVersion
from knowledge_base.documents.creator import DocumentCreator
from knowledge_base.documents.approval import ApprovalConfig, ApprovalWorkflow
from knowledge_base.documents.models import (
    ApprovalDecision,
    DocumentArea,
    DocumentType,
    DocumentStatus,
    SourceType,
)

pytestmark = pytest.mark.integration


# =============================================================================
# Fixtures for sync database access
# =============================================================================


@pytest.fixture
def sync_db():
    """Create a sync in-memory SQLite database."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    yield session

    session.close()
    engine.dispose()


@pytest.fixture
def test_users():
    """Test user IDs."""
    return {
        "author": "U_AUTHOR_001",
        "approver_1": "U_APPROVER_001",
        "approver_2": "U_APPROVER_002",
        "approver_3": "U_APPROVER_003",
        "random_user": "U_RANDOM_001",
    }


@pytest.fixture
def mock_llm():
    """Mock LLM with predictable responses."""
    llm = MagicMock()

    async def generate_content(prompt: str) -> str:
        if "improve" in prompt.lower() or "feedback" in prompt.lower():
            return """## Purpose
This policy establishes comprehensive guidelines.

## Safety Precautions
Added based on feedback.

## Rollback Procedures
Added rollback steps as requested.

---
### Suggestions
- Consider adding examples"""
        return """## Generated Content

This is AI-generated content for testing.

---
### Suggestions
- Review for accuracy"""

    llm.generate = AsyncMock(side_effect=generate_content)
    return llm


@pytest.fixture
def mock_slack():
    """Mock Slack client that tracks messages."""
    slack = MagicMock()
    slack.sent_messages = []

    async def track_message(**kwargs):
        slack.sent_messages.append({
            "channel": kwargs.get("channel"),
            "text": kwargs.get("text", ""),
            "blocks": kwargs.get("blocks"),
        })
        return {"ok": True, "ts": "1234567890.123456"}

    slack.chat_postMessage = AsyncMock(side_effect=track_message)
    return slack


@pytest.fixture
def db_with_approvers(sync_db, test_users):
    """Database with pre-configured approvers."""
    approvers = [
        (DocumentArea.ENGINEERING.value, test_users["approver_1"], "Approver One"),
        (DocumentArea.ENGINEERING.value, test_users["approver_2"], "Approver Two"),
        (DocumentArea.FINANCE.value, test_users["approver_1"], "Approver One"),
        (DocumentArea.PEOPLE.value, test_users["approver_3"], "Approver Three"),
    ]

    for area, approver_id, name in approvers:
        approver = AreaApprover(
            area=area,
            approver_slack_id=approver_id,
            approver_name=name,
            is_active=True,
            added_by="U_ADMIN",
            added_at=datetime.utcnow(),
        )
        sync_db.add(approver)

    sync_db.commit()
    return sync_db


@pytest.fixture
def creator(db_with_approvers, mock_llm, mock_slack):
    """DocumentCreator with real DB, mock LLM and Slack."""
    config = ApprovalConfig(
        require_all_approvers=False,
        auto_approve_updates=False,
        expiry_days=14,
    )

    return DocumentCreator(
        session=db_with_approvers,
        llm=mock_llm,
        approval_config=config,
        slack_client=mock_slack,
    )


# =============================================================================
# Full Approval Workflow Tests
# =============================================================================


class TestApprovalWorkflowIntegration:
    """Integration tests for the full approval workflow."""

    @pytest.mark.asyncio
    async def test_policy_full_approval_workflow(self, creator, test_users, mock_slack):
        """Test: Draft -> Submit for approval -> Approve -> Publish.

        Workflow:
        1. Author creates a policy document (draft status)
        2. Author submits for approval (in_review status)
        3. Approver approves (approved status)
        4. Document is published (published status)
        """
        # Step 1: Create policy document
        doc = await creator.create_manual(
            title="Data Retention Policy",
            content="All data must be retained for 7 years...",
            area=DocumentArea.ENGINEERING,
            doc_type=DocumentType.POLICY,
            created_by=test_users["author"],
        )

        assert doc.status == DocumentStatus.DRAFT.value
        assert doc.doc_id is not None
        assert doc.title == "Data Retention Policy"

        # Step 2: Submit for approval
        doc = await creator.submit_for_approval(
            doc_id=doc.doc_id,
            submitted_by=test_users["author"],
        )

        assert doc.status == DocumentStatus.IN_REVIEW.value

        # Verify Slack notification was sent to approvers
        assert len(mock_slack.sent_messages) >= 1
        assert any(
            "Approval Request" in msg.get("text", "")
            for msg in mock_slack.sent_messages
        )

        # Step 3: Approver approves
        decision = ApprovalDecision(
            doc_id=doc.doc_id,
            approved=True,
            approver_id=test_users["approver_1"],
        )

        status = await creator.approval.process_decision(decision)

        assert status.status == DocumentStatus.APPROVED.value
        assert test_users["approver_1"] in status.approved_by

        # Step 4: Publish
        doc = await creator.publish_document(doc.doc_id)

        assert doc.status == DocumentStatus.PUBLISHED.value
        assert doc.published_at is not None

        # Verify version was created
        stmt = select(DocumentVersion).where(DocumentVersion.doc_id == doc.doc_id)
        result = creator.session.execute(stmt)
        versions = list(result.scalars().all())
        assert len(versions) == 1
        assert versions[0].version == 1

    @pytest.mark.asyncio
    async def test_rejection_and_resubmit_workflow(
        self, creator, test_users, mock_slack
    ):
        """Test: Draft -> Submit -> Reject -> Improve -> Resubmit -> Approve.

        Verifies the feedback loop when documents need revision.
        """
        # Step 1: Create and submit document
        doc = await creator.create_manual(
            title="Incomplete Procedure",
            content="Step 1: Do something...",
            area=DocumentArea.ENGINEERING,
            doc_type=DocumentType.PROCEDURE,
            created_by=test_users["author"],
        )

        doc = await creator.submit_for_approval(
            doc_id=doc.doc_id,
            submitted_by=test_users["author"],
        )

        assert doc.status == DocumentStatus.IN_REVIEW.value

        # Step 2: Approver rejects with feedback
        mock_slack.sent_messages.clear()

        rejection = ApprovalDecision(
            doc_id=doc.doc_id,
            approved=False,
            approver_id=test_users["approver_1"],
            rejection_reason="Missing safety precautions and rollback steps",
        )

        status = await creator.approval.process_decision(rejection)

        assert status.status == DocumentStatus.REJECTED.value
        assert status.rejected_by == test_users["approver_1"]
        assert "safety precautions" in status.rejection_reason

        # Verify rejection notification sent to author
        assert any(
            "Rejected" in msg.get("text", "")
            for msg in mock_slack.sent_messages
        )

        # Step 3: Author improves the document
        doc, draft_result = await creator.improve_draft(
            doc_id=doc.doc_id,
            feedback="Add safety precautions and rollback procedures",
            improved_by=test_users["author"],
        )

        assert doc.status == DocumentStatus.DRAFT.value
        assert doc.rejection_reason is None  # Cleared after improvement

        # Step 4: Resubmit for approval
        doc = await creator.submit_for_approval(
            doc_id=doc.doc_id,
            submitted_by=test_users["author"],
        )

        assert doc.status == DocumentStatus.IN_REVIEW.value

        # Step 5: Approver approves improved version
        approval = ApprovalDecision(
            doc_id=doc.doc_id,
            approved=True,
            approver_id=test_users["approver_1"],
        )

        status = await creator.approval.process_decision(approval)

        assert status.status == DocumentStatus.APPROVED.value


# =============================================================================
# Auto-Publish Tests
# =============================================================================


class TestAutoPublishIntegration:
    """Tests for documents that don't require approval."""

    @pytest.mark.asyncio
    async def test_information_auto_publishes(self, creator, test_users):
        """Test that INFORMATION documents auto-publish."""
        doc = await creator.create_manual(
            title="Office Locations",
            content="Our offices are located in...",
            area=DocumentArea.GENERAL,
            doc_type=DocumentType.INFORMATION,
            created_by=test_users["author"],
        )

        # Should be auto-published
        assert doc.status == DocumentStatus.PUBLISHED.value

    @pytest.mark.asyncio
    async def test_guideline_auto_publishes(self, creator, test_users):
        """Test that GUIDELINE documents auto-publish."""
        doc = await creator.create_manual(
            title="Code Review Best Practices",
            content="When reviewing code, consider...",
            area=DocumentArea.ENGINEERING,
            doc_type=DocumentType.GUIDELINE,
            created_by=test_users["author"],
        )

        # Should be auto-published
        assert doc.status == DocumentStatus.PUBLISHED.value

    @pytest.mark.asyncio
    async def test_policy_stays_draft(self, creator, test_users):
        """Test that POLICY documents stay in draft."""
        doc = await creator.create_manual(
            title="Security Policy",
            content="All employees must...",
            area=DocumentArea.ENGINEERING,
            doc_type=DocumentType.POLICY,
            created_by=test_users["author"],
        )

        # Should stay in draft
        assert doc.status == DocumentStatus.DRAFT.value


# =============================================================================
# Multiple Approver Tests
# =============================================================================


class TestMultipleApproversIntegration:
    """Tests for multiple approver scenarios."""

    @pytest.mark.asyncio
    async def test_single_approval_sufficient(self, creator, test_users):
        """Test that single approval is sufficient when require_all_approvers=False."""
        # Engineering area has 2 approvers configured
        doc = await creator.create_manual(
            title="Test Policy",
            content="Policy content...",
            area=DocumentArea.ENGINEERING,
            doc_type=DocumentType.POLICY,
            created_by=test_users["author"],
        )

        await creator.submit_for_approval(doc.doc_id, test_users["author"])

        # Only one approver approves
        decision = ApprovalDecision(
            doc_id=doc.doc_id,
            approved=True,
            approver_id=test_users["approver_1"],
        )

        status = await creator.approval.process_decision(decision)

        # Should be fully approved with just one approval
        assert status.status == DocumentStatus.APPROVED.value
        assert len(status.approved_by) == 1

    @pytest.mark.asyncio
    async def test_require_all_approvers(
        self, db_with_approvers, mock_llm, mock_slack, test_users
    ):
        """Test that all approvers must approve when require_all_approvers=True."""
        # Create creator with require_all_approvers=True
        config = ApprovalConfig(require_all_approvers=True)
        creator = DocumentCreator(
            session=db_with_approvers,
            llm=mock_llm,
            approval_config=config,
            slack_client=mock_slack,
        )

        doc = await creator.create_manual(
            title="Critical Policy",
            content="This policy requires consensus...",
            area=DocumentArea.ENGINEERING,  # Has 2 approvers
            doc_type=DocumentType.POLICY,
            created_by=test_users["author"],
        )

        await creator.submit_for_approval(doc.doc_id, test_users["author"])

        # First approval - should still be pending
        decision1 = ApprovalDecision(
            doc_id=doc.doc_id,
            approved=True,
            approver_id=test_users["approver_1"],
        )

        status = await creator.approval.process_decision(decision1)

        # Still in review - waiting for second approver
        assert status.status == DocumentStatus.IN_REVIEW.value
        assert test_users["approver_1"] in status.approved_by
        assert len(status.pending_approvers) > 0

        # Second approval - should complete
        decision2 = ApprovalDecision(
            doc_id=doc.doc_id,
            approved=True,
            approver_id=test_users["approver_2"],
        )

        status = await creator.approval.process_decision(decision2)

        assert status.status == DocumentStatus.APPROVED.value
        assert test_users["approver_1"] in status.approved_by
        assert test_users["approver_2"] in status.approved_by


# =============================================================================
# Document Update Tests
# =============================================================================


class TestDocumentUpdateIntegration:
    """Tests for document update workflows."""

    @pytest.mark.asyncio
    async def test_update_published_requires_reapproval(self, creator, test_users):
        """Test that updating a published policy moves it back to draft."""
        # Create, approve, and publish a policy
        doc = await creator.create_manual(
            title="Living Policy",
            content="Original content v1",
            area=DocumentArea.FINANCE,
            doc_type=DocumentType.POLICY,
            created_by=test_users["author"],
        )

        await creator.submit_for_approval(doc.doc_id, test_users["author"])

        await creator.approval.process_decision(
            ApprovalDecision(
                doc_id=doc.doc_id,
                approved=True,
                approver_id=test_users["approver_1"],
            )
        )

        await creator.publish_document(doc.doc_id)

        # Verify published
        doc = creator.get_document(doc.doc_id)
        assert doc.status == DocumentStatus.PUBLISHED.value

        # Now update the published document
        updated_doc = await creator.update_document(
            doc_id=doc.doc_id,
            content="Updated content v2 with significant changes",
            updated_by=test_users["author"],
        )

        # Should be back in draft, requiring re-approval
        assert updated_doc.status == DocumentStatus.DRAFT.value
        assert updated_doc.updated_by == test_users["author"]
        assert updated_doc.updated_at is not None


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCasesIntegration:
    """Integration tests for edge cases and error scenarios."""

    @pytest.mark.asyncio
    async def test_area_without_approvers(self, creator, test_users):
        """Test submission when area has no approvers configured.

        GENERAL area has no approvers in configured_approvers.
        """
        doc = await creator.create_manual(
            title="General Policy",
            content="Policy for general area...",
            area=DocumentArea.GENERAL,
            doc_type=DocumentType.POLICY,
            created_by=test_users["author"],
        )

        # Submit for approval
        doc = await creator.submit_for_approval(
            doc_id=doc.doc_id,
            submitted_by=test_users["author"],
        )

        # Should be in review but with empty approvers list
        assert doc.status == DocumentStatus.IN_REVIEW.value

        # Get status to verify pending_approvers is empty
        status = creator.approval.get_approval_status(doc.doc_id)
        assert status.pending_approvers == []

    @pytest.mark.asyncio
    async def test_unauthorized_approval_attempt(self, creator, test_users):
        """Test that non-approvers cannot approve documents."""
        doc = await creator.create_manual(
            title="Test Policy",
            content="Content...",
            area=DocumentArea.ENGINEERING,
            doc_type=DocumentType.POLICY,
            created_by=test_users["author"],
        )

        await creator.submit_for_approval(doc.doc_id, test_users["author"])

        # Random user tries to approve
        decision = ApprovalDecision(
            doc_id=doc.doc_id,
            approved=True,
            approver_id=test_users["random_user"],
        )

        with pytest.raises(ValueError, match="not authorized"):
            await creator.approval.process_decision(decision)

    @pytest.mark.asyncio
    async def test_cannot_approve_draft_document(self, creator, test_users):
        """Test that approval fails for documents not in review status."""
        # Create document in draft (don't submit)
        doc = await creator.create_manual(
            title="Draft Only",
            content="Not submitted yet",
            area=DocumentArea.ENGINEERING,
            doc_type=DocumentType.POLICY,
            created_by=test_users["author"],
        )

        assert doc.status == DocumentStatus.DRAFT.value

        # Try to approve draft directly
        decision = ApprovalDecision(
            doc_id=doc.doc_id,
            approved=True,
            approver_id=test_users["approver_1"],
        )

        with pytest.raises(ValueError, match="not in review"):
            await creator.approval.process_decision(decision)

    @pytest.mark.asyncio
    async def test_document_not_found(self, creator, test_users):
        """Test error when document doesn't exist."""
        decision = ApprovalDecision(
            doc_id="nonexistent-doc-id",
            approved=True,
            approver_id=test_users["approver_1"],
        )

        with pytest.raises(ValueError, match="not found"):
            await creator.approval.process_decision(decision)


# =============================================================================
# Version History Tests
# =============================================================================


class TestVersionHistoryIntegration:
    """Tests for document version history."""

    @pytest.mark.asyncio
    async def test_version_created_on_approval(self, creator, test_users):
        """Test that version is created when document is approved."""
        doc = await creator.create_manual(
            title="Versioned Policy",
            content="Version 1 content",
            area=DocumentArea.FINANCE,
            doc_type=DocumentType.POLICY,
            created_by=test_users["author"],
        )

        await creator.submit_for_approval(doc.doc_id, test_users["author"])
        await creator.approval.process_decision(
            ApprovalDecision(
                doc_id=doc.doc_id,
                approved=True,
                approver_id=test_users["approver_1"],
            )
        )

        # Check version 1 created
        stmt = select(DocumentVersion).where(DocumentVersion.doc_id == doc.doc_id)
        result = creator.session.execute(stmt)
        versions = list(result.scalars().all())

        assert len(versions) == 1
        assert versions[0].version == 1
        assert versions[0].content == "Version 1 content"

    @pytest.mark.asyncio
    async def test_multiple_versions_tracked(self, creator, test_users):
        """Test that multiple approval cycles create multiple versions."""
        doc = await creator.create_manual(
            title="Versioned Policy",
            content="Version 1 content",
            area=DocumentArea.FINANCE,
            doc_type=DocumentType.POLICY,
            created_by=test_users["author"],
        )

        # First approval cycle
        await creator.submit_for_approval(doc.doc_id, test_users["author"])
        await creator.approval.process_decision(
            ApprovalDecision(
                doc_id=doc.doc_id,
                approved=True,
                approver_id=test_users["approver_1"],
            )
        )

        # Publish and update
        await creator.publish_document(doc.doc_id)
        await creator.update_document(
            doc_id=doc.doc_id,
            content="Version 2 content with updates",
            updated_by=test_users["author"],
        )

        # Second approval cycle
        await creator.submit_for_approval(doc.doc_id, test_users["author"])
        await creator.approval.process_decision(
            ApprovalDecision(
                doc_id=doc.doc_id,
                approved=True,
                approver_id=test_users["approver_1"],
            )
        )

        # Check version 2 created
        stmt = (
            select(DocumentVersion)
            .where(DocumentVersion.doc_id == doc.doc_id)
            .order_by(DocumentVersion.version)
        )
        result = creator.session.execute(stmt)
        versions = list(result.scalars().all())

        assert len(versions) == 2
        assert versions[0].version == 1
        assert versions[1].version == 2
        assert "Version 2" in versions[1].content


# =============================================================================
# Slack Notification Tests
# =============================================================================


class TestSlackNotificationsIntegration:
    """Tests to verify Slack notifications are triggered correctly."""

    @pytest.mark.asyncio
    async def test_approval_request_notifications(
        self, creator, test_users, mock_slack
    ):
        """Verify notifications sent to all area approvers on submission."""
        doc = await creator.create_manual(
            title="New Policy",
            content="Policy requiring approval...",
            area=DocumentArea.ENGINEERING,  # 2 approvers
            doc_type=DocumentType.POLICY,
            created_by=test_users["author"],
        )

        mock_slack.sent_messages.clear()
        await creator.submit_for_approval(doc.doc_id, test_users["author"])

        # Should have sent notifications to both approvers
        notified_channels = [m["channel"] for m in mock_slack.sent_messages]
        assert test_users["approver_1"] in notified_channels
        assert test_users["approver_2"] in notified_channels

        # Verify message content
        for msg in mock_slack.sent_messages:
            assert "Approval Request" in msg["text"]

    @pytest.mark.asyncio
    async def test_rejection_notification_to_author(
        self, creator, test_users, mock_slack
    ):
        """Verify author receives notification on rejection."""
        doc = await creator.create_manual(
            title="Test Policy",
            content="Content...",
            area=DocumentArea.FINANCE,
            doc_type=DocumentType.POLICY,
            created_by=test_users["author"],
        )

        await creator.submit_for_approval(doc.doc_id, test_users["author"])
        mock_slack.sent_messages.clear()

        await creator.approval.process_decision(
            ApprovalDecision(
                doc_id=doc.doc_id,
                approved=False,
                approver_id=test_users["approver_1"],
                rejection_reason="Needs more detail",
            )
        )

        # Find rejection notification to author
        rejection_msgs = [
            m
            for m in mock_slack.sent_messages
            if m["channel"] == test_users["author"]
        ]

        assert len(rejection_msgs) == 1
        assert "Rejected" in rejection_msgs[0]["text"]
        assert "Needs more detail" in rejection_msgs[0]["text"]


# =============================================================================
# AI Integration Tests
# =============================================================================


class TestAIIntegration:
    """Tests for AI-generated document creation with real DB."""

    @pytest.mark.asyncio
    async def test_create_from_description(self, creator, test_users, mock_llm):
        """Test AI-generated document is saved correctly."""
        doc, draft_result = await creator.create_from_description(
            title="AI Generated Policy",
            description="Create a policy about code review practices",
            area=DocumentArea.ENGINEERING,
            doc_type=DocumentType.POLICY,
            created_by=test_users["author"],
        )

        assert doc.status == DocumentStatus.DRAFT.value
        assert doc.source_type == SourceType.AI_DRAFT.value
        assert draft_result.confidence > 0
        assert len(doc.content) > 0

        # Verify LLM was called
        mock_llm.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_from_thread(self, creator, test_users, mock_llm):
        """Test thread summary document is saved correctly."""
        messages = [
            {"user": "U001", "text": "How do we handle deployments?"},
            {"user": "U002", "text": "We use CI/CD pipeline with staging first."},
            {"user": "U001", "text": "What about rollbacks?"},
            {"user": "U002", "text": "Automated rollback on failure."},
        ]

        doc, draft_result = await creator.create_from_thread(
            thread_messages=messages,
            channel_id="C_TEST_CHANNEL",
            thread_ts="1234567890.123456",
            area=DocumentArea.ENGINEERING,
            created_by=test_users["author"],
        )

        assert doc.source_type == SourceType.THREAD_SUMMARY.value
        assert doc.source_thread_ts == "1234567890.123456"
        assert doc.source_channel_id == "C_TEST_CHANNEL"


# =============================================================================
# Database Isolation Tests
# =============================================================================


class TestDatabaseIsolation:
    """Verify test isolation - each test gets a fresh database."""

    @pytest.mark.asyncio
    async def test_isolation_first(self, sync_db):
        """First test creates a document."""
        doc = Document(
            doc_id="isolation-test-1",
            title="Isolation Test",
            content="Content",
            area="general",
            doc_type="information",
            status="published",
            created_by="U_TEST",
        )
        sync_db.add(doc)
        sync_db.commit()

        # Verify document exists
        stmt = select(Document).where(Document.doc_id == "isolation-test-1")
        result = sync_db.execute(stmt)
        assert result.scalars().first() is not None

    @pytest.mark.asyncio
    async def test_isolation_second(self, sync_db):
        """Second test should NOT see document from first test."""
        stmt = select(Document).where(Document.doc_id == "isolation-test-1")
        result = sync_db.execute(stmt)

        # Document from previous test should not exist
        assert result.scalars().first() is None
