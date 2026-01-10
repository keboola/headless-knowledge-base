"""Document creation module for knowledge base.

This module provides functionality for:
- AI-powered document drafting from descriptions and Slack threads
- Manual document creation
- Approval workflows for policies and procedures
- Document lifecycle management (draft, review, approve, publish, archive)
"""

from knowledge_base.documents.ai_drafter import AIDrafter, DraftResult
from knowledge_base.documents.approval import (
    ApprovalConfig,
    ApprovalStatus,
    ApprovalWorkflow,
)
from knowledge_base.documents.creator import DocumentCreator
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

__all__ = [
    # Creator
    "DocumentCreator",
    # AI Drafter
    "AIDrafter",
    "DraftResult",
    # Approval
    "ApprovalConfig",
    "ApprovalStatus",
    "ApprovalWorkflow",
    # Models
    "APPROVAL_REQUIRED",
    "ApprovalDecision",
    "ApprovalRequest",
    "Classification",
    "DocumentArea",
    "DocumentDraft",
    "DocumentStatus",
    "DocumentType",
    "SourceType",
    "requires_approval",
]
