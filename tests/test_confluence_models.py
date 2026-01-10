"""Tests for Confluence models."""

from datetime import datetime

import pytest

from knowledge_base.confluence.models import (
    Attachment,
    GovernanceInfo,
    Page,
    PageContent,
    Permission,
)


class TestGovernanceInfo:
    """Tests for GovernanceInfo extraction from labels."""

    def test_from_labels_empty(self):
        """Test extraction from empty labels."""
        gov = GovernanceInfo.from_labels([])
        assert gov.owner is None
        assert gov.reviewed_by is None
        assert gov.reviewed_at is None
        assert gov.classification == "internal"  # default
        assert gov.doc_type is None

    def test_from_labels_owner(self):
        """Test owner extraction."""
        gov = GovernanceInfo.from_labels(["owner:john.doe"])
        assert gov.owner == "john.doe"

    def test_from_labels_reviewed_by(self):
        """Test reviewed-by extraction."""
        gov = GovernanceInfo.from_labels(["reviewed-by:jane.smith"])
        assert gov.reviewed_by == "jane.smith"

    def test_from_labels_reviewed_at(self):
        """Test reviewed date extraction."""
        gov = GovernanceInfo.from_labels(["reviewed:2024-01-15"])
        assert gov.reviewed_at is not None
        assert gov.reviewed_at.year == 2024
        assert gov.reviewed_at.month == 1
        assert gov.reviewed_at.day == 15

    def test_from_labels_classification(self):
        """Test classification extraction."""
        gov = GovernanceInfo.from_labels(["confidential"])
        assert gov.classification == "confidential"

        gov = GovernanceInfo.from_labels(["public"])
        assert gov.classification == "public"

    def test_from_labels_doc_type(self):
        """Test doc_type extraction."""
        gov = GovernanceInfo.from_labels(["policy"])
        assert gov.doc_type == "policy"

        gov = GovernanceInfo.from_labels(["procedure"])
        assert gov.doc_type == "procedure"

    def test_from_labels_full(self):
        """Test full extraction with all labels."""
        labels = [
            "owner:john.doe",
            "reviewed-by:jane.smith",
            "reviewed:2024-06-01",
            "confidential",
            "policy",
            "some-other-label",
        ]
        gov = GovernanceInfo.from_labels(labels)
        assert gov.owner == "john.doe"
        assert gov.reviewed_by == "jane.smith"
        assert gov.reviewed_at.year == 2024
        assert gov.classification == "confidential"
        assert gov.doc_type == "policy"

    def test_from_labels_case_insensitive(self):
        """Test that label matching is case-insensitive."""
        gov = GovernanceInfo.from_labels(["Owner:john.doe", "CONFIDENTIAL"])
        assert gov.owner == "john.doe"
        assert gov.classification == "confidential"

    def test_from_labels_invalid_date(self):
        """Test handling of invalid date format."""
        gov = GovernanceInfo.from_labels(["reviewed:not-a-date"])
        assert gov.reviewed_at is None


class TestPermission:
    """Tests for Permission model."""

    def test_permission_creation(self):
        """Test creating a permission."""
        perm = Permission(type="user", name="john.doe", operation="read")
        assert perm.type == "user"
        assert perm.name == "john.doe"
        assert perm.operation == "read"


class TestAttachment:
    """Tests for Attachment model."""

    def test_attachment_creation(self):
        """Test creating an attachment."""
        att = Attachment(
            id="att-123",
            title="document.pdf",
            media_type="application/pdf",
            file_size=1024,
            download_url="https://example.com/download/att-123",
        )
        assert att.id == "att-123"
        assert att.title == "document.pdf"
        assert att.media_type == "application/pdf"
        assert att.file_size == 1024


class TestPage:
    """Tests for Page model."""

    def test_page_creation(self):
        """Test creating a page."""
        page = Page(
            id="page-123",
            title="Test Page",
            space_key="TEST",
            url="https://example.com/page/123",
            status="current",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            author="john.doe",
        )
        assert page.id == "page-123"
        assert page.title == "Test Page"
        assert page.parent_id is None  # default


class TestPageContent:
    """Tests for PageContent model."""

    def test_page_content_creation(self):
        """Test creating page content."""
        content = PageContent(
            id="page-123",
            title="Test Page",
            space_key="TEST",
            url="https://example.com/page/123",
            html_content="<p>Hello World</p>",
            author="john.doe",
            author_name="John Doe",
            parent_id=None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            version_number=5,
            status="current",
        )
        assert content.id == "page-123"
        assert content.html_content == "<p>Hello World</p>"
        assert content.author_name == "John Doe"
        assert content.version_number == 5
        assert content.labels == []  # default
        assert content.permissions == []  # default
        assert content.attachments == []  # default
