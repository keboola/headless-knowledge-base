"""Tests for the document creation module."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from knowledge_base.documents.models import (
    APPROVAL_REQUIRED,
    ApprovalDecision,
    ApprovalRequest,
    Classification,
    DocumentArea,
    DocumentDraft,
    DocumentStatus,
    DocumentType,
    SourceType,
    requires_approval,
)
from knowledge_base.documents.ai_drafter import AIDrafter, DraftResult
from knowledge_base.documents.approval import (
    ApprovalConfig,
    ApprovalStatus,
    ApprovalWorkflow,
)
from knowledge_base.documents.creator import DocumentCreator


# =============================================================================
# Model Tests
# =============================================================================


class TestDocumentArea:
    """Tests for DocumentArea enum."""

    def test_values(self):
        """Test all area values exist."""
        assert DocumentArea.PEOPLE.value == "people"
        assert DocumentArea.FINANCE.value == "finance"
        assert DocumentArea.ENGINEERING.value == "engineering"
        assert DocumentArea.OPERATIONS.value == "operations"
        assert DocumentArea.GENERAL.value == "general"

    def test_string_conversion(self):
        """Test string conversion via value."""
        assert DocumentArea.PEOPLE.value == "people"


class TestDocumentType:
    """Tests for DocumentType enum."""

    def test_values(self):
        """Test all type values exist."""
        assert DocumentType.POLICY.value == "policy"
        assert DocumentType.PROCEDURE.value == "procedure"
        assert DocumentType.GUIDELINE.value == "guideline"
        assert DocumentType.INFORMATION.value == "information"


class TestClassification:
    """Tests for Classification enum."""

    def test_values(self):
        """Test all classification values exist."""
        assert Classification.PUBLIC.value == "public"
        assert Classification.INTERNAL.value == "internal"
        assert Classification.CONFIDENTIAL.value == "confidential"


class TestDocumentStatus:
    """Tests for DocumentStatus enum."""

    def test_values(self):
        """Test all status values exist."""
        assert DocumentStatus.DRAFT.value == "draft"
        assert DocumentStatus.IN_REVIEW.value == "in_review"
        assert DocumentStatus.APPROVED.value == "approved"
        assert DocumentStatus.PUBLISHED.value == "published"
        assert DocumentStatus.REJECTED.value == "rejected"
        assert DocumentStatus.ARCHIVED.value == "archived"


class TestSourceType:
    """Tests for SourceType enum."""

    def test_values(self):
        """Test all source type values exist."""
        assert SourceType.MANUAL.value == "manual"
        assert SourceType.THREAD_SUMMARY.value == "thread_summary"
        assert SourceType.AI_DRAFT.value == "ai_draft"


class TestApprovalRequired:
    """Tests for APPROVAL_REQUIRED dict."""

    def test_policy_requires_approval(self):
        """Test policy requires approval."""
        assert APPROVAL_REQUIRED[DocumentType.POLICY] is True

    def test_procedure_requires_approval(self):
        """Test procedure requires approval."""
        assert APPROVAL_REQUIRED[DocumentType.PROCEDURE] is True

    def test_guideline_no_approval(self):
        """Test guideline doesn't require approval."""
        assert APPROVAL_REQUIRED[DocumentType.GUIDELINE] is False

    def test_information_no_approval(self):
        """Test information doesn't require approval."""
        assert APPROVAL_REQUIRED[DocumentType.INFORMATION] is False


class TestRequiresApproval:
    """Tests for requires_approval function."""

    def test_with_enum(self):
        """Test with DocumentType enum."""
        assert requires_approval(DocumentType.POLICY) is True
        assert requires_approval(DocumentType.GUIDELINE) is False

    def test_with_string(self):
        """Test with string value."""
        assert requires_approval("policy") is True
        assert requires_approval("information") is False

    def test_unknown_type_defaults_to_true(self):
        """Test unknown type defaults to requiring approval."""
        assert requires_approval("unknown_type") is True


class TestDocumentDraft:
    """Tests for DocumentDraft dataclass."""

    def test_creation_with_enums(self):
        """Test creating draft with enum values."""
        draft = DocumentDraft(
            title="Test Policy",
            content="This is test content",
            area=DocumentArea.ENGINEERING,
            doc_type=DocumentType.POLICY,
        )
        assert draft.title == "Test Policy"
        assert draft.area == DocumentArea.ENGINEERING
        assert draft.classification == Classification.INTERNAL

    def test_creation_with_strings(self):
        """Test creating draft with string values (auto-converted)."""
        draft = DocumentDraft(
            title="Test",
            content="Content",
            area="finance",
            doc_type="procedure",
            classification="confidential",
        )
        assert draft.area == DocumentArea.FINANCE
        assert draft.doc_type == DocumentType.PROCEDURE
        assert draft.classification == Classification.CONFIDENTIAL

    def test_source_fields(self):
        """Test source tracking fields."""
        draft = DocumentDraft(
            title="Thread Summary",
            content="Summary content",
            area=DocumentArea.GENERAL,
            doc_type=DocumentType.INFORMATION,
            source_type=SourceType.THREAD_SUMMARY,
            source_thread_ts="1234567890.123456",
            source_channel_id="C123ABC",
        )
        assert draft.source_type == SourceType.THREAD_SUMMARY
        assert draft.source_thread_ts == "1234567890.123456"


class TestApprovalRequest:
    """Tests for ApprovalRequest dataclass."""

    def test_creation(self):
        """Test creating approval request."""
        request = ApprovalRequest(
            doc_id="doc123",
            title="New Policy",
            content_preview="This policy covers...",
            area="engineering",
            doc_type="policy",
            created_by="U123ABC",
            approvers=["U456DEF", "U789GHI"],
        )
        assert request.doc_id == "doc123"
        assert len(request.approvers) == 2
        assert request.requested_at is not None


class TestApprovalDecision:
    """Tests for ApprovalDecision dataclass."""

    def test_approval(self):
        """Test approval decision."""
        decision = ApprovalDecision(
            doc_id="doc123",
            approved=True,
            approver_id="U456DEF",
        )
        assert decision.approved is True
        assert decision.rejection_reason is None

    def test_rejection(self):
        """Test rejection decision."""
        decision = ApprovalDecision(
            doc_id="doc123",
            approved=False,
            approver_id="U456DEF",
            rejection_reason="Missing compliance section",
        )
        assert decision.approved is False
        assert decision.rejection_reason == "Missing compliance section"


# =============================================================================
# AI Drafter Tests
# =============================================================================


class TestAIDrafter:
    """Tests for AIDrafter class."""

    @pytest.fixture
    def mock_llm(self):
        """Create a mock LLM."""
        llm = MagicMock()
        llm.generate = AsyncMock(return_value="Generated content here")
        return llm

    @pytest.fixture
    def drafter(self, mock_llm):
        """Create a drafter with mock LLM."""
        return AIDrafter(mock_llm)

    @pytest.mark.asyncio
    async def test_draft_from_description(self, drafter, mock_llm):
        """Test drafting from a description."""
        result = await drafter.draft_from_description(
            title="VPN Configuration Policy",
            description="Policy for how employees should configure VPN",
            area=DocumentArea.ENGINEERING,
            doc_type=DocumentType.POLICY,
        )

        assert isinstance(result, DraftResult)
        assert result.draft.title == "VPN Configuration Policy"
        assert result.draft.area == DocumentArea.ENGINEERING
        assert result.draft.source_type == SourceType.AI_DRAFT
        assert result.confidence == 0.8
        mock_llm.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_draft_from_description_with_strings(self, drafter, mock_llm):
        """Test drafting with string enum values."""
        result = await drafter.draft_from_description(
            title="Test",
            description="Test description",
            area="finance",
            doc_type="guideline",
            classification="confidential",
        )

        assert result.draft.area == DocumentArea.FINANCE
        assert result.draft.doc_type == DocumentType.GUIDELINE
        assert result.draft.classification == Classification.CONFIDENTIAL

    @pytest.mark.asyncio
    async def test_draft_from_thread(self, drafter, mock_llm):
        """Test drafting from a Slack thread."""
        mock_llm.generate = AsyncMock(
            return_value="# How to Reset Password\n\nStep 1: Go to settings..."
        )

        messages = [
            {"user": "U123", "text": "How do I reset my password?"},
            {"user": "U456", "text": "Go to settings, then security..."},
        ]

        result = await drafter.draft_from_thread(
            thread_messages=messages,
            channel_id="C123ABC",
            thread_ts="1234567890.123456",
            area=DocumentArea.OPERATIONS,
        )

        assert result.draft.title == "How to Reset Password"
        assert result.draft.source_type == SourceType.THREAD_SUMMARY
        assert result.draft.source_thread_ts == "1234567890.123456"
        assert result.confidence == 0.7

    @pytest.mark.asyncio
    async def test_improve_draft(self, drafter, mock_llm):
        """Test improving a draft with feedback."""
        mock_llm.generate = AsyncMock(return_value="Improved content here")

        original = DocumentDraft(
            title="Test Doc",
            content="Original content",
            area=DocumentArea.GENERAL,
            doc_type=DocumentType.INFORMATION,
        )

        result = await drafter.improve_draft(
            draft=original,
            feedback="Add more details about X",
        )

        assert result.draft.content == "Improved content here"
        assert result.confidence == 0.85

    def test_extract_suggestions(self, drafter):
        """Test extracting suggestions from content."""
        content = """Main content here.

## Suggestions
- Add more examples
- Clarify the scope
"""
        main, suggestions = drafter._extract_suggestions(content)

        assert "Main content here" in main
        assert len(suggestions) == 2
        assert "Add more examples" in suggestions

    def test_extract_title_content(self, drafter):
        """Test extracting title and content."""
        text = """# My Document Title

This is the content.
"""
        title, content = drafter._extract_title_content(text)

        assert title == "My Document Title"
        assert "This is the content" in content

    def test_format_thread(self, drafter):
        """Test formatting Slack thread messages."""
        messages = [
            {"user": "U123", "text": "Hello"},
            {"user": "U456", "text": "Hi there"},
        ]
        formatted = drafter._format_thread(messages)

        assert "[U123]: Hello" in formatted
        assert "[U456]: Hi there" in formatted


# =============================================================================
# Approval Workflow Tests
# =============================================================================


class TestApprovalConfig:
    """Tests for ApprovalConfig dataclass."""

    def test_defaults(self):
        """Test default configuration."""
        config = ApprovalConfig()
        assert config.require_all_approvers is False
        assert config.auto_approve_updates is False
        assert config.expiry_days == 14

    def test_custom(self):
        """Test custom configuration."""
        config = ApprovalConfig(
            require_all_approvers=True,
            expiry_days=7,
        )
        assert config.require_all_approvers is True
        assert config.expiry_days == 7


class TestApprovalStatus:
    """Tests for ApprovalStatus dataclass."""

    def test_pending_status(self):
        """Test pending approval status."""
        status = ApprovalStatus(
            doc_id="doc123",
            status="pending",
            pending_approvers=["U123", "U456"],
        )
        assert status.status == "pending"
        assert len(status.pending_approvers) == 2

    def test_rejected_status(self):
        """Test rejected approval status."""
        status = ApprovalStatus(
            doc_id="doc123",
            status="rejected",
            rejected_by="U789",
            rejection_reason="Incomplete",
        )
        assert status.rejected_by == "U789"


class TestApprovalWorkflow:
    """Tests for ApprovalWorkflow class."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.execute = MagicMock()
        session.add = MagicMock()
        session.commit = MagicMock()
        return session

    @pytest.fixture
    def workflow(self, mock_session):
        """Create a workflow with mock session."""
        return ApprovalWorkflow(mock_session)

    def test_needs_approval_policy(self, workflow):
        """Test policy needs approval."""
        assert workflow.needs_approval(DocumentType.POLICY) is True

    def test_needs_approval_information(self, workflow):
        """Test information doesn't need approval."""
        assert workflow.needs_approval(DocumentType.INFORMATION) is False

    def test_needs_approval_string(self, workflow):
        """Test with string value."""
        assert workflow.needs_approval("procedure") is True

    def test_get_approvers_empty(self, workflow, mock_session):
        """Test getting approvers when none exist."""
        mock_session.execute.return_value.scalars.return_value.all.return_value = []

        approvers = workflow.get_approvers(DocumentArea.ENGINEERING)
        assert approvers == []

    def test_get_approvers(self, workflow, mock_session):
        """Test getting approvers."""
        mock_approver = MagicMock()
        mock_approver.approver_slack_id = "U123ABC"
        mock_session.execute.return_value.scalars.return_value.all.return_value = [
            mock_approver
        ]

        approvers = workflow.get_approvers(DocumentArea.ENGINEERING)
        assert approvers == ["U123ABC"]

    def test_add_approver(self, workflow, mock_session):
        """Test adding an approver."""
        result = workflow.add_approver(
            area=DocumentArea.FINANCE,
            slack_user_id="U456DEF",
            added_by="U123ABC",
        )

        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()

    def test_get_approval_status_not_found(self, workflow, mock_session):
        """Test getting status for non-existent document."""
        mock_session.execute.return_value.scalars.return_value.first.return_value = None

        status = workflow.get_approval_status("nonexistent")
        assert status is None

    def test_get_pending_approvals(self, workflow, mock_session):
        """Test getting pending approvals for a user."""
        import json
        mock_doc = MagicMock()
        mock_doc.status = "in_review"
        mock_doc.pending_approvers = json.dumps(["U123ABC"])  # JSON string
        mock_session.execute.return_value.scalars.return_value.all.return_value = [
            mock_doc
        ]

        pending = workflow.get_pending_approvals("U123ABC")
        assert len(pending) == 1


# =============================================================================
# Document Creator Tests
# =============================================================================


class TestDocumentCreator:
    """Tests for DocumentCreator class."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.execute = MagicMock()
        session.add = MagicMock()
        session.commit = MagicMock()
        return session

    @pytest.fixture
    def mock_llm(self):
        """Create a mock LLM."""
        llm = MagicMock()
        llm.generate = AsyncMock(return_value="Generated content")
        return llm

    @pytest.fixture
    def creator(self, mock_session, mock_llm):
        """Create a DocumentCreator with mocks."""
        return DocumentCreator(mock_session, mock_llm)

    @pytest.fixture
    def creator_no_llm(self, mock_session):
        """Create a DocumentCreator without LLM."""
        return DocumentCreator(mock_session)

    @pytest.mark.asyncio
    async def test_create_manual(self, creator, mock_session):
        """Test creating a document manually."""
        doc = await creator.create_manual(
            title="Manual Doc",
            content="Some content",
            area=DocumentArea.GENERAL,
            doc_type=DocumentType.INFORMATION,
            created_by="U123ABC",
        )

        assert doc.title == "Manual Doc"
        assert doc.status == "published"  # Information auto-publishes
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_manual_policy(self, creator, mock_session):
        """Test creating a policy manually (stays draft)."""
        doc = await creator.create_manual(
            title="New Policy",
            content="Policy content",
            area=DocumentArea.FINANCE,
            doc_type=DocumentType.POLICY,
            created_by="U123ABC",
        )

        assert doc.status == "draft"

    @pytest.mark.asyncio
    async def test_create_from_description(self, creator, mock_llm):
        """Test creating from description with AI."""
        doc, draft_result = await creator.create_from_description(
            title="AI Generated",
            description="Create a doc about X",
            area=DocumentArea.ENGINEERING,
            doc_type=DocumentType.GUIDELINE,
            created_by="U123ABC",
        )

        assert doc.title == "AI Generated"
        assert draft_result is not None
        assert draft_result.confidence > 0

    @pytest.mark.asyncio
    async def test_create_from_description_no_llm(self, creator_no_llm):
        """Test create_from_description without LLM raises error."""
        with pytest.raises(ValueError, match="LLM not configured"):
            await creator_no_llm.create_from_description(
                title="Test",
                description="Test",
                area=DocumentArea.GENERAL,
                doc_type=DocumentType.INFORMATION,
                created_by="U123",
            )

    @pytest.mark.asyncio
    async def test_create_from_thread(self, creator, mock_llm):
        """Test creating from Slack thread."""
        mock_llm.generate = AsyncMock(
            return_value="# Thread Summary\n\nContent from thread..."
        )

        messages = [
            {"user": "U123", "text": "Question here"},
            {"user": "U456", "text": "Answer here"},
        ]

        doc, draft_result = await creator.create_from_thread(
            thread_messages=messages,
            channel_id="C123",
            thread_ts="1234567890.123456",
            area=DocumentArea.OPERATIONS,
            created_by="U789",
        )

        assert doc.source_thread_ts == "1234567890.123456"
        assert draft_result.draft.source_type == SourceType.THREAD_SUMMARY

    def test_get_document(self, creator, mock_session):
        """Test getting a document by ID."""
        mock_doc = MagicMock()
        mock_doc.id = "doc123"
        mock_session.execute.return_value.scalars.return_value.first.return_value = (
            mock_doc
        )

        doc = creator.get_document("doc123")
        assert doc.id == "doc123"

    def test_get_document_not_found(self, creator, mock_session):
        """Test getting non-existent document."""
        mock_session.execute.return_value.scalars.return_value.first.return_value = None

        doc = creator.get_document("nonexistent")
        assert doc is None

    def test_list_documents(self, creator, mock_session):
        """Test listing documents."""
        mock_docs = [MagicMock(), MagicMock()]
        mock_session.execute.return_value.scalars.return_value.all.return_value = (
            mock_docs
        )

        docs = creator.list_documents(area=DocumentArea.ENGINEERING)
        assert len(docs) == 2

    def test_search_documents(self, creator, mock_session):
        """Test searching documents."""
        mock_docs = [MagicMock()]
        mock_session.execute.return_value.scalars.return_value.all.return_value = (
            mock_docs
        )

        docs = creator.search_documents("VPN")
        assert len(docs) == 1

    @pytest.mark.asyncio
    async def test_archive_document(self, creator, mock_session):
        """Test archiving a document."""
        mock_doc = MagicMock()
        mock_doc.id = "doc123"
        mock_doc.status = "published"
        mock_session.execute.return_value.scalars.return_value.first.return_value = (
            mock_doc
        )

        doc = await creator.archive_document(
            doc_id="doc123",
            archived_by="U123ABC",
            reason="Outdated",
        )

        assert doc.status == "archived"
        assert doc.archive_reason == "Outdated"


# =============================================================================
# Integration-like Tests
# =============================================================================


class TestDraftResult:
    """Tests for DraftResult dataclass."""

    def test_creation(self):
        """Test creating a draft result."""
        draft = DocumentDraft(
            title="Test",
            content="Content",
            area=DocumentArea.GENERAL,
            doc_type=DocumentType.INFORMATION,
        )
        result = DraftResult(
            draft=draft,
            confidence=0.85,
            suggestions=["Add more details"],
        )

        assert result.confidence == 0.85
        assert len(result.suggestions) == 1


class TestDocumentLifecycle:
    """Test the full document lifecycle."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.execute = MagicMock()
        session.add = MagicMock()
        session.commit = MagicMock()
        return session

    @pytest.mark.asyncio
    async def test_information_doc_auto_publishes(self, mock_session):
        """Test that information docs are auto-published."""
        creator = DocumentCreator(mock_session)

        doc = await creator.create_manual(
            title="FAQ",
            content="Questions and answers",
            area=DocumentArea.GENERAL,
            doc_type=DocumentType.INFORMATION,
            created_by="U123",
        )

        assert doc.status == "published"

    @pytest.mark.asyncio
    async def test_policy_stays_draft(self, mock_session):
        """Test that policies stay in draft."""
        creator = DocumentCreator(mock_session)

        doc = await creator.create_manual(
            title="Security Policy",
            content="Policy content",
            area=DocumentArea.ENGINEERING,
            doc_type=DocumentType.POLICY,
            created_by="U123",
        )

        assert doc.status == "draft"
