"""Approval workflow for documents requiring sign-off."""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_base.db.models import AreaApprover, Document, DocumentVersion
from knowledge_base.documents.models import (
    ApprovalDecision,
    ApprovalRequest,
    DocumentArea,
    DocumentStatus,
    DocumentType,
    requires_approval,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _json_to_list(value: str | None) -> list[str]:
    """Convert JSON string to list."""
    if not value:
        return []
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []


def _list_to_json(value: list[str]) -> str:
    """Convert list to JSON string."""
    return json.dumps(value)


@dataclass
class ApprovalConfig:
    """Configuration for approval workflow."""

    require_all_approvers: bool = False  # If True, all must approve; else any one
    auto_approve_updates: bool = False  # Auto-approve minor updates
    expiry_days: int = 14  # Days before approval request expires


@dataclass
class ApprovalStatus:
    """Status of an approval request."""

    doc_id: str
    status: str  # pending, approved, rejected, expired
    pending_approvers: list[str] = field(default_factory=list)
    approved_by: list[str] = field(default_factory=list)
    rejected_by: str | None = None
    rejection_reason: str | None = None
    requested_at: datetime | None = None
    decided_at: datetime | None = None


class ApprovalWorkflow:
    """Manages document approval workflows.

    Handles:
    - Determining required approvers by area
    - Sending approval requests
    - Processing approval decisions
    - Tracking approval status
    """

    def __init__(
        self,
        session: Session,
        config: ApprovalConfig | None = None,
        slack_client=None,
    ):
        """Initialize the approval workflow.

        Args:
            session: Database session
            config: Approval configuration
            slack_client: Optional Slack client for notifications
        """
        self.session = session
        self.config = config or ApprovalConfig()
        self.slack_client = slack_client

    def needs_approval(self, doc_type: DocumentType | str) -> bool:
        """Check if a document type requires approval.

        Args:
            doc_type: Document type to check

        Returns:
            True if approval is required
        """
        return requires_approval(doc_type)

    def get_approvers(self, area: DocumentArea | str) -> list[str]:
        """Get list of approvers for an area.

        Args:
            area: Document area

        Returns:
            List of approver Slack user IDs
        """
        if isinstance(area, str):
            area = DocumentArea(area)

        stmt = select(AreaApprover).where(
            AreaApprover.area == area.value,
            AreaApprover.is_active == True,  # noqa: E712
        )
        result = self.session.execute(stmt)
        approvers = result.scalars().all()

        return [a.approver_slack_id for a in approvers]

    def add_approver(
        self,
        area: DocumentArea | str,
        slack_user_id: str,
        added_by: str,
    ) -> AreaApprover:
        """Add an approver for an area.

        Args:
            area: Document area
            slack_user_id: Slack user ID of the approver
            added_by: User ID of who added this approver

        Returns:
            The created AreaApprover record
        """
        if isinstance(area, str):
            area = DocumentArea(area)

        approver = AreaApprover(
            area=area.value,
            approver_slack_id=slack_user_id,
            added_by=added_by,
        )
        self.session.add(approver)
        self.session.commit()

        logger.info(f"Added approver {slack_user_id} for area {area.value}")
        return approver

    def remove_approver(self, area: DocumentArea | str, slack_user_id: str) -> bool:
        """Remove an approver from an area.

        Args:
            area: Document area
            slack_user_id: Slack user ID to remove

        Returns:
            True if approver was found and removed
        """
        if isinstance(area, str):
            area = DocumentArea(area)

        stmt = select(AreaApprover).where(
            AreaApprover.area == area.value,
            AreaApprover.approver_slack_id == slack_user_id,
        )
        result = self.session.execute(stmt)
        approver = result.scalars().first()

        if approver:
            approver.is_active = False
            self.session.commit()
            logger.info(f"Removed approver {slack_user_id} from area {area.value}")
            return True

        return False

    async def request_approval(
        self,
        document: Document,
        requested_by: str,
    ) -> ApprovalRequest:
        """Create an approval request for a document.

        Args:
            document: Document requiring approval
            requested_by: User ID of the requester

        Returns:
            ApprovalRequest object
        """
        approvers = self.get_approvers(document.area)

        if not approvers:
            logger.warning(f"No approvers configured for area {document.area}")
            # Fall back to a default behavior - auto-approve or raise?
            approvers = []

        # Update document status
        document.status = DocumentStatus.IN_REVIEW.value
        document.pending_approvers = _list_to_json(approvers)
        self.session.commit()

        request = ApprovalRequest(
            doc_id=document.doc_id,
            title=document.title,
            content_preview=document.content[:500] if document.content else "",
            area=document.area,
            doc_type=document.doc_type,
            created_by=requested_by,
            approvers=approvers,
        )

        # Send notifications if Slack client is available
        if self.slack_client and approvers:
            await self._notify_approvers(request)

        logger.info(
            f"Created approval request for doc {document.doc_id}, "
            f"approvers: {approvers}"
        )
        return request

    async def process_decision(
        self,
        decision: ApprovalDecision,
    ) -> ApprovalStatus:
        """Process an approval decision.

        Args:
            decision: The approval decision

        Returns:
            Updated approval status
        """
        # Get the document
        stmt = select(Document).where(Document.doc_id == decision.doc_id)
        result = self.session.execute(stmt)
        document = result.scalars().first()

        if not document:
            raise ValueError(f"Document {decision.doc_id} not found")

        if document.status != DocumentStatus.IN_REVIEW.value:
            raise ValueError(
                f"Document {decision.doc_id} is not in review "
                f"(status: {document.status})"
            )

        # Check if user is authorized to approve
        pending = _json_to_list(document.pending_approvers)
        approved_by = _json_to_list(document.approved_by)

        if decision.approver_id not in pending and decision.approver_id not in approved_by:
            # Allow if they're a valid approver for the area
            area_approvers = self.get_approvers(document.area)
            if decision.approver_id not in area_approvers:
                raise ValueError(
                    f"User {decision.approver_id} is not authorized to approve "
                    f"documents in area {document.area}"
                )

        if decision.approved:
            return await self._handle_approval(document, decision)
        else:
            return await self._handle_rejection(document, decision)

    async def _handle_approval(
        self,
        document: Document,
        decision: ApprovalDecision,
    ) -> ApprovalStatus:
        """Handle an approval decision."""
        pending = _json_to_list(document.pending_approvers)
        approved_by = _json_to_list(document.approved_by)

        # Move from pending to approved
        if decision.approver_id in pending:
            pending.remove(decision.approver_id)
        if decision.approver_id not in approved_by:
            approved_by.append(decision.approver_id)

        document.pending_approvers = _list_to_json(pending)
        document.approved_by = _list_to_json(approved_by)

        # Check if fully approved
        if self.config.require_all_approvers:
            # Need all original approvers
            area_approvers = set(self.get_approvers(document.area))
            approved_set = set(approved_by)
            is_approved = area_approvers.issubset(approved_set)
        else:
            # Just need one approval
            is_approved = len(approved_by) > 0

        if is_approved:
            document.status = DocumentStatus.APPROVED.value
            document.approved_at = decision.decided_at

            # Create a version record
            self._create_version(document, decision.approver_id)

            # Notify requester
            if self.slack_client:
                await self._notify_approval(document)

            logger.info(f"Document {document.doc_id} approved by {decision.approver_id}")
        else:
            logger.info(
                f"Document {document.doc_id} partially approved by {decision.approver_id}, "
                f"waiting for: {pending}"
            )

        self.session.commit()

        return ApprovalStatus(
            doc_id=document.doc_id,
            status=document.status,
            pending_approvers=pending,
            approved_by=approved_by,
            decided_at=decision.decided_at,
        )

    async def _handle_rejection(
        self,
        document: Document,
        decision: ApprovalDecision,
    ) -> ApprovalStatus:
        """Handle a rejection decision."""
        document.status = DocumentStatus.REJECTED.value
        document.rejection_reason = decision.rejection_reason
        document.rejected_by = decision.approver_id
        document.rejected_at = decision.decided_at

        self.session.commit()

        # Notify requester
        if self.slack_client:
            await self._notify_rejection(document, decision)

        logger.info(
            f"Document {document.doc_id} rejected by {decision.approver_id}: "
            f"{decision.rejection_reason}"
        )

        return ApprovalStatus(
            doc_id=document.doc_id,
            status=document.status,
            rejected_by=decision.approver_id,
            rejection_reason=decision.rejection_reason,
            decided_at=decision.decided_at,
        )

    def get_approval_status(self, doc_id: str) -> ApprovalStatus | None:
        """Get the approval status of a document.

        Args:
            doc_id: Document ID

        Returns:
            ApprovalStatus or None if document not found
        """
        stmt = select(Document).where(Document.doc_id == doc_id)
        result = self.session.execute(stmt)
        document = result.scalars().first()

        if not document:
            return None

        return ApprovalStatus(
            doc_id=document.doc_id,
            status=document.status,
            pending_approvers=_json_to_list(document.pending_approvers),
            approved_by=_json_to_list(document.approved_by),
            rejected_by=document.rejected_by,
            rejection_reason=document.rejection_reason,
            requested_at=document.created_at,
            decided_at=document.approved_at or document.rejected_at,
        )

    def get_pending_approvals(self, approver_id: str) -> list[Document]:
        """Get documents pending approval by a user.

        Args:
            approver_id: Slack user ID of the approver

        Returns:
            List of documents awaiting their approval
        """
        stmt = select(Document).where(
            Document.status == DocumentStatus.IN_REVIEW.value,
        )
        result = self.session.execute(stmt)
        documents = result.scalars().all()

        # Filter to those where this user is a pending approver
        pending = []
        for doc in documents:
            pending_approvers = _json_to_list(doc.pending_approvers)
            if approver_id in pending_approvers:
                pending.append(doc)

        return pending

    def _create_version(self, document: Document, approved_by: str) -> DocumentVersion:
        """Create a version record for an approved document."""
        # Get current version number
        stmt = select(DocumentVersion).where(
            DocumentVersion.doc_id == document.doc_id
        ).order_by(DocumentVersion.version.desc())
        result = self.session.execute(stmt)
        latest = result.scalars().first()

        version_num = (latest.version + 1) if latest else 1

        version = DocumentVersion(
            doc_id=document.doc_id,
            version=version_num,
            title=document.title,
            content=document.content,
            changed_by=approved_by,
            change_summary="Approved",
        )
        self.session.add(version)

        document.version = version_num
        return version

    async def _notify_approvers(self, request: ApprovalRequest) -> None:
        """Send approval request notifications to approvers."""
        if not self.slack_client:
            return

        for approver_id in request.approvers:
            try:
                message = (
                    f"📋 *Approval Request*\n\n"
                    f"A new {request.doc_type} document needs your approval:\n\n"
                    f"*Title:* {request.title}\n"
                    f"*Area:* {request.area}\n"
                    f"*Requested by:* <@{request.created_by}>\n\n"
                    f"_Preview:_\n>{request.content_preview[:200]}..."
                )

                await self.slack_client.chat_postMessage(
                    channel=approver_id,
                    text=message,
                    blocks=[
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": message},
                        },
                        {
                            "type": "actions",
                            "elements": [
                                {
                                    "type": "button",
                                    "text": {"type": "plain_text", "text": "✅ Approve"},
                                    "style": "primary",
                                    "action_id": f"approve_doc_{request.doc_id}",
                                },
                                {
                                    "type": "button",
                                    "text": {"type": "plain_text", "text": "❌ Reject"},
                                    "style": "danger",
                                    "action_id": f"reject_doc_{request.doc_id}",
                                },
                                {
                                    "type": "button",
                                    "text": {"type": "plain_text", "text": "👁️ View Full"},
                                    "action_id": f"view_doc_{request.doc_id}",
                                },
                            ],
                        },
                    ],
                )
            except Exception as e:
                logger.error(f"Failed to notify approver {approver_id}: {e}")

    async def _notify_approval(self, document: Document) -> None:
        """Notify document creator of approval."""
        if not self.slack_client or not document.created_by:
            return

        try:
            message = (
                f"✅ *Document Approved*\n\n"
                f"Your document *{document.title}* has been approved!\n\n"
                f"Approved by: {', '.join(f'<@{u}>' for u in (document.approved_by or []))}"
            )

            await self.slack_client.chat_postMessage(
                channel=document.created_by,
                text=message,
            )
        except Exception as e:
            logger.error(f"Failed to send approval notification: {e}")

    async def _notify_rejection(
        self,
        document: Document,
        decision: ApprovalDecision,
    ) -> None:
        """Notify document creator of rejection."""
        if not self.slack_client or not document.created_by:
            return

        try:
            message = (
                f"❌ *Document Rejected*\n\n"
                f"Your document *{document.title}* was rejected by <@{decision.approver_id}>.\n\n"
                f"*Reason:* {decision.rejection_reason or 'No reason provided'}\n\n"
                f"Please address the feedback and resubmit for approval."
            )

            await self.slack_client.chat_postMessage(
                channel=document.created_by,
                text=message,
            )
        except Exception as e:
            logger.error(f"Failed to send rejection notification: {e}")
