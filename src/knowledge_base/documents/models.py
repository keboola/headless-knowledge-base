"""Data models and enums for document creation."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class DocumentArea(str, Enum):
    """Document areas for governance."""

    PEOPLE = "people"
    FINANCE = "finance"
    ENGINEERING = "engineering"
    OPERATIONS = "operations"
    GENERAL = "general"


class DocumentType(str, Enum):
    """Types of documents with different approval requirements."""

    POLICY = "policy"  # Requires approval
    PROCEDURE = "procedure"  # Requires approval
    GUIDELINE = "guideline"  # No approval needed
    INFORMATION = "information"  # No approval needed


class Classification(str, Enum):
    """Document classification levels."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"


class DocumentStatus(str, Enum):
    """Document lifecycle status."""

    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    PUBLISHED = "published"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class SourceType(str, Enum):
    """How the document was created."""

    MANUAL = "manual"
    THREAD_SUMMARY = "thread_summary"
    AI_DRAFT = "ai_draft"


# Document types that require approval
APPROVAL_REQUIRED = {
    DocumentType.POLICY: True,
    DocumentType.PROCEDURE: True,
    DocumentType.GUIDELINE: False,
    DocumentType.INFORMATION: False,
}


def requires_approval(doc_type: DocumentType | str) -> bool:
    """Check if a document type requires approval.

    Args:
        doc_type: Document type (enum or string)

    Returns:
        True if approval is required
    """
    if isinstance(doc_type, str):
        try:
            doc_type = DocumentType(doc_type)
        except ValueError:
            return True  # Default to requiring approval for unknown types

    return APPROVAL_REQUIRED.get(doc_type, True)


@dataclass
class DocumentDraft:
    """A draft document before creation."""

    title: str
    content: str
    area: DocumentArea | str
    doc_type: DocumentType | str
    classification: Classification | str = Classification.INTERNAL
    source_type: SourceType | str = SourceType.MANUAL
    source_thread_ts: str | None = None
    source_channel_id: str | None = None

    def __post_init__(self):
        """Convert string values to enums."""
        if isinstance(self.area, str):
            self.area = DocumentArea(self.area)
        if isinstance(self.doc_type, str):
            self.doc_type = DocumentType(self.doc_type)
        if isinstance(self.classification, str):
            self.classification = Classification(self.classification)
        if isinstance(self.source_type, str):
            self.source_type = SourceType(self.source_type)


@dataclass
class ApprovalRequest:
    """An approval request for a document."""

    doc_id: str
    title: str
    content_preview: str
    area: str
    doc_type: str
    created_by: str
    approvers: list[str] = field(default_factory=list)
    requested_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ApprovalDecision:
    """A decision on a document approval request."""

    doc_id: str
    approved: bool
    approver_id: str
    decided_at: datetime = field(default_factory=datetime.utcnow)
    rejection_reason: str | None = None
