"""Document creation and management."""

import logging
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_base.db.models import Document
from knowledge_base.documents.ai_drafter import AIDrafter, DraftResult
from knowledge_base.documents.approval import ApprovalConfig, ApprovalWorkflow
from knowledge_base.documents.models import (
    Classification,
    DocumentArea,
    DocumentDraft,
    DocumentStatus,
    DocumentType,
    SourceType,
    requires_approval,
)

if TYPE_CHECKING:
    from knowledge_base.llm.base import BaseLLM

logger = logging.getLogger(__name__)


class DocumentCreator:
    """Creates and manages documents in the knowledge base.

    Orchestrates:
    - AI drafting from descriptions or threads
    - Manual document creation
    - Approval workflow for policies/procedures
    - Document publishing
    """

    def __init__(
        self,
        session: Session,
        llm: "BaseLLM | None" = None,
        approval_config: ApprovalConfig | None = None,
        slack_client=None,
    ):
        """Initialize the document creator.

        Args:
            session: Database session
            llm: Language model for AI drafting (optional)
            approval_config: Approval workflow configuration
            slack_client: Slack client for notifications
        """
        self.session = session
        self.llm = llm
        self.slack_client = slack_client

        # Initialize sub-components
        self.drafter = AIDrafter(llm) if llm else None
        self.approval = ApprovalWorkflow(session, approval_config, slack_client)

    async def create_from_description(
        self,
        title: str,
        description: str,
        area: DocumentArea | str,
        doc_type: DocumentType | str,
        created_by: str,
        classification: Classification | str = Classification.INTERNAL,
    ) -> tuple[Document, DraftResult | None]:
        """Create a document from a description using AI.

        Args:
            title: Document title
            description: What the document should cover
            area: Document area
            doc_type: Type of document
            created_by: User ID who created the document
            classification: Security classification

        Returns:
            Tuple of (Document, DraftResult) if AI drafted, (Document, None) if manual
        """
        if not self.drafter:
            raise ValueError("LLM not configured for AI drafting")

        # Generate draft
        draft_result = await self.drafter.draft_from_description(
            title=title,
            description=description,
            area=area,
            doc_type=doc_type,
            classification=classification,
        )

        # Create document from draft
        document = await self._create_document(draft_result.draft, created_by)

        logger.info(
            f"Created document {document.id} from description, "
            f"confidence: {draft_result.confidence}"
        )

        return document, draft_result

    async def create_from_thread(
        self,
        thread_messages: list[dict],
        channel_id: str,
        thread_ts: str,
        area: DocumentArea | str,
        created_by: str,
        doc_type: DocumentType | str = DocumentType.INFORMATION,
        classification: Classification | str = Classification.INTERNAL,
    ) -> tuple[Document, DraftResult]:
        """Create a document from a Slack thread.

        Args:
            thread_messages: List of messages from the thread
            channel_id: Slack channel ID
            thread_ts: Thread timestamp
            area: Document area
            created_by: User ID who created the document
            doc_type: Type of document
            classification: Security classification

        Returns:
            Tuple of (Document, DraftResult)
        """
        if not self.drafter:
            raise ValueError("LLM not configured for AI drafting")

        # Generate draft from thread
        draft_result = await self.drafter.draft_from_thread(
            thread_messages=thread_messages,
            channel_id=channel_id,
            thread_ts=thread_ts,
            area=area,
            doc_type=doc_type,
            classification=classification,
        )

        # Create document from draft
        document = await self._create_document(draft_result.draft, created_by)

        logger.info(
            f"Created document {document.id} from thread {thread_ts}, "
            f"confidence: {draft_result.confidence}"
        )

        return document, draft_result

    async def create_manual(
        self,
        title: str,
        content: str,
        area: DocumentArea | str,
        doc_type: DocumentType | str,
        created_by: str,
        classification: Classification | str = Classification.INTERNAL,
    ) -> Document:
        """Create a document manually (no AI).

        Args:
            title: Document title
            content: Document content
            area: Document area
            doc_type: Type of document
            created_by: User ID who created the document
            classification: Security classification

        Returns:
            Created Document
        """
        draft = DocumentDraft(
            title=title,
            content=content,
            area=area,
            doc_type=doc_type,
            classification=classification,
            source_type=SourceType.MANUAL,
        )

        document = await self._create_document(draft, created_by)

        logger.info(f"Created manual document {document.id}")

        return document

    async def _create_document(
        self,
        draft: DocumentDraft,
        created_by: str,
    ) -> Document:
        """Create a document from a draft.

        Args:
            draft: The document draft
            created_by: User ID who created the document

        Returns:
            Created Document
        """
        # Determine initial status
        needs_approval = requires_approval(draft.doc_type)
        initial_status = (
            DocumentStatus.DRAFT.value
            if needs_approval
            else DocumentStatus.PUBLISHED.value
        )

        # Create document record
        document = Document(
            doc_id=str(uuid.uuid4()),
            title=draft.title,
            content=draft.content,
            area=draft.area.value if isinstance(draft.area, DocumentArea) else draft.area,
            doc_type=draft.doc_type.value if isinstance(draft.doc_type, DocumentType) else draft.doc_type,
            classification=draft.classification.value if isinstance(draft.classification, Classification) else draft.classification,
            source_type=draft.source_type.value if isinstance(draft.source_type, SourceType) else draft.source_type,
            source_thread_ts=draft.source_thread_ts,
            source_channel_id=draft.source_channel_id,
            status=initial_status,
            created_by=created_by,
        )

        self.session.add(document)
        self.session.commit()

        return document

    async def submit_for_approval(
        self,
        doc_id: str,
        submitted_by: str,
    ) -> Document:
        """Submit a draft document for approval.

        Args:
            doc_id: Document ID
            submitted_by: User ID submitting for approval

        Returns:
            Updated Document

        Raises:
            ValueError: If document not found or not in draft status
        """
        document = self._get_document(doc_id)

        if document.status != DocumentStatus.DRAFT.value:
            raise ValueError(
                f"Document must be in draft status to submit for approval "
                f"(current: {document.status})"
            )

        # Check if approval is needed
        if not requires_approval(document.doc_type):
            # Auto-publish
            document.status = DocumentStatus.PUBLISHED.value
            document.published_at = datetime.utcnow()
            self.session.commit()
            logger.info(f"Document {doc_id} auto-published (no approval needed)")
            return document

        # Request approval
        await self.approval.request_approval(document, submitted_by)

        return document

    async def update_document(
        self,
        doc_id: str,
        content: str,
        updated_by: str,
        title: str | None = None,
    ) -> Document:
        """Update an existing document.

        Args:
            doc_id: Document ID
            content: New content
            updated_by: User ID making the update
            title: New title (optional)

        Returns:
            Updated Document
        """
        document = self._get_document(doc_id)

        # Update fields
        document.content = content
        if title:
            document.title = title
        document.updated_at = datetime.utcnow()
        document.updated_by = updated_by

        # If published, may need re-approval
        if document.status == DocumentStatus.PUBLISHED.value:
            if requires_approval(document.doc_type):
                document.status = DocumentStatus.DRAFT.value
                logger.info(f"Document {doc_id} moved back to draft after update")

        self.session.commit()

        return document

    async def publish_document(self, doc_id: str) -> Document:
        """Publish an approved document.

        Args:
            doc_id: Document ID

        Returns:
            Published Document

        Raises:
            ValueError: If document not approved
        """
        document = self._get_document(doc_id)

        if document.status not in [DocumentStatus.APPROVED.value, DocumentStatus.DRAFT.value]:
            raise ValueError(
                f"Document must be approved or draft to publish "
                f"(current: {document.status})"
            )

        # Check if approval was needed and received
        if requires_approval(document.doc_type):
            if document.status != DocumentStatus.APPROVED.value:
                raise ValueError("Document requires approval before publishing")

        document.status = DocumentStatus.PUBLISHED.value
        document.published_at = datetime.utcnow()
        self.session.commit()

        logger.info(f"Document {doc_id} published")

        return document

    async def archive_document(
        self,
        doc_id: str,
        archived_by: str,
        reason: str | None = None,
    ) -> Document:
        """Archive a document.

        Args:
            doc_id: Document ID
            archived_by: User ID archiving the document
            reason: Optional reason for archiving

        Returns:
            Archived Document
        """
        document = self._get_document(doc_id)

        document.status = DocumentStatus.ARCHIVED.value
        document.archived_at = datetime.utcnow()
        document.archived_by = archived_by
        document.archive_reason = reason

        self.session.commit()

        logger.info(f"Document {doc_id} archived by {archived_by}: {reason}")

        return document

    def get_document(self, doc_id: str) -> Document | None:
        """Get a document by ID.

        Args:
            doc_id: Document ID

        Returns:
            Document or None
        """
        stmt = select(Document).where(Document.doc_id == doc_id)
        result = self.session.execute(stmt)
        return result.scalars().first()

    def _get_document(self, doc_id: str) -> Document:
        """Get a document by ID, raising if not found."""
        document = self.get_document(doc_id)
        if not document:
            raise ValueError(f"Document {doc_id} not found")
        return document

    def list_documents(
        self,
        area: DocumentArea | str | None = None,
        doc_type: DocumentType | str | None = None,
        status: DocumentStatus | str | None = None,
        created_by: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Document]:
        """List documents with optional filtering.

        Args:
            area: Filter by area
            doc_type: Filter by document type
            status: Filter by status
            created_by: Filter by creator
            limit: Maximum results
            offset: Result offset

        Returns:
            List of matching documents
        """
        stmt = select(Document)

        if area:
            area_val = area.value if isinstance(area, DocumentArea) else area
            stmt = stmt.where(Document.area == area_val)

        if doc_type:
            type_val = doc_type.value if isinstance(doc_type, DocumentType) else doc_type
            stmt = stmt.where(Document.doc_type == type_val)

        if status:
            status_val = status.value if isinstance(status, DocumentStatus) else status
            stmt = stmt.where(Document.status == status_val)

        if created_by:
            stmt = stmt.where(Document.created_by == created_by)

        stmt = stmt.order_by(Document.created_at.desc()).limit(limit).offset(offset)

        result = self.session.execute(stmt)
        return list(result.scalars().all())

    def search_documents(
        self,
        query: str,
        area: DocumentArea | str | None = None,
        limit: int = 20,
    ) -> list[Document]:
        """Search documents by title/content.

        Args:
            query: Search query
            area: Optional area filter
            limit: Maximum results

        Returns:
            List of matching documents
        """
        stmt = select(Document).where(
            Document.status == DocumentStatus.PUBLISHED.value,
        )

        if area:
            area_val = area.value if isinstance(area, DocumentArea) else area
            stmt = stmt.where(Document.area == area_val)

        # Simple text search (could be enhanced with FTS)
        stmt = stmt.where(
            Document.title.ilike(f"%{query}%") | Document.content.ilike(f"%{query}%")
        )

        stmt = stmt.limit(limit)

        result = self.session.execute(stmt)
        return list(result.scalars().all())

    async def improve_draft(
        self,
        doc_id: str,
        feedback: str,
        improved_by: str,
    ) -> tuple[Document, DraftResult]:
        """Improve a draft document based on feedback.

        Args:
            doc_id: Document ID
            feedback: Improvement feedback
            improved_by: User ID providing feedback

        Returns:
            Tuple of (updated Document, DraftResult)
        """
        if not self.drafter:
            raise ValueError("LLM not configured for AI drafting")

        document = self._get_document(doc_id)

        if document.status not in [DocumentStatus.DRAFT.value, DocumentStatus.REJECTED.value]:
            raise ValueError(
                f"Can only improve drafts or rejected documents "
                f"(current: {document.status})"
            )

        # Create a draft from current content
        current_draft = DocumentDraft(
            title=document.title,
            content=document.content,
            area=document.area,
            doc_type=document.doc_type,
            classification=document.classification,
            source_type=document.source_type,
            source_thread_ts=document.source_thread_ts,
            source_channel_id=document.source_channel_id,
        )

        # Improve with AI
        draft_result = await self.drafter.improve_draft(current_draft, feedback)

        # Update document
        document.content = draft_result.draft.content
        document.updated_at = datetime.utcnow()
        document.updated_by = improved_by

        # Reset to draft if was rejected
        if document.status == DocumentStatus.REJECTED.value:
            document.status = DocumentStatus.DRAFT.value
            document.rejection_reason = None
            document.rejected_by = None
            document.rejected_at = None

        self.session.commit()

        logger.info(f"Improved document {doc_id} based on feedback")

        return document, draft_result
