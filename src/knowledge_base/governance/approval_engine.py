"""Approval engine for knowledge governance status transitions.

Manages the lifecycle of governance decisions:
- Records decisions in SQLite (source of truth for governance status)
- Updates Neo4j episode metadata (for search filtering)
- Provides admin query methods (pending queue, revertable items)

See ADR-0011 for design rationale.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select

from knowledge_base.config import settings
from knowledge_base.db.database import async_session_maker
from knowledge_base.db.models import KnowledgeGovernanceRecord
from knowledge_base.governance.risk_classifier import RiskAssessment
from knowledge_base.vectorstore.indexer import ChunkData

logger = logging.getLogger(__name__)


@dataclass
class GovernanceResult:
    """Result of a governance submission."""

    status: str  # "auto_approved", "pending_review", "approved_with_revert"
    risk_assessment: RiskAssessment
    revert_deadline: Optional[datetime] = None
    records: list[KnowledgeGovernanceRecord] = field(default_factory=list)


class ApprovalEngine:
    """Manages governance status transitions in Neo4j + SQLite.

    SQLite is the source of truth for governance status. Neo4j episode
    metadata is updated as a side effect for search filtering, but failures
    there do not block the governance workflow.
    """

    async def submit(
        self,
        chunks: list[ChunkData],
        assessment: RiskAssessment,
        submitted_by: str,
        intake_path: str,
    ) -> GovernanceResult:
        """Record governance decision for new content.

        Creates KnowledgeGovernanceRecord entries in SQLite.
        The chunks should already have governance_status set on them
        before being indexed to Graphiti.

        Returns GovernanceResult with status and revert deadline.
        """
        # Determine status based on tier
        if assessment.tier == "low":
            status = "auto_approved"
            revert_deadline = None
        elif assessment.tier == "medium":
            status = "auto_approved"  # Medium is auto-approved with revert window
            revert_deadline = datetime.utcnow() + timedelta(
                hours=settings.GOVERNANCE_REVERT_WINDOW_HOURS
            )
        else:  # high
            status = "pending_review"
            revert_deadline = None

        records = []
        async with async_session_maker() as session:
            for chunk in chunks:
                record = KnowledgeGovernanceRecord(
                    chunk_id=chunk.chunk_id,
                    risk_score=assessment.score,
                    risk_tier=assessment.tier,
                    risk_factors=json.dumps(assessment.factors),
                    intake_path=intake_path,
                    submitted_by=submitted_by,
                    content_preview=chunk.content[:300] if chunk.content else "",
                    status=status,
                    revert_deadline=revert_deadline,
                )
                session.add(record)
                records.append(record)
            await session.commit()

        result_status = "approved_with_revert" if assessment.tier == "medium" else status
        return GovernanceResult(
            status=result_status,
            risk_assessment=assessment,
            revert_deadline=revert_deadline,
            records=records,
        )

    async def approve(self, chunk_id: str, reviewed_by: str, note: str = "") -> bool:
        """Admin approves pending content. Updates SQLite + Neo4j.

        Returns True if successful, False if chunk not found or not pending.
        """
        async with async_session_maker() as session:
            result = await session.execute(
                select(KnowledgeGovernanceRecord).where(
                    KnowledgeGovernanceRecord.chunk_id == chunk_id,
                    KnowledgeGovernanceRecord.status == "pending_review",
                )
            )
            record = result.scalar_one_or_none()
            if not record:
                logger.warning(f"Cannot approve {chunk_id}: not found or not pending")
                return False

            record.status = "approved"
            record.reviewed_by = reviewed_by
            record.reviewed_at = datetime.utcnow()
            record.review_note = note
            await session.commit()

        # Update Neo4j episode metadata
        await self._update_neo4j_governance_status(chunk_id, "approved")
        logger.info(f"Approved content {chunk_id}")
        logger.debug(f"Approved by {reviewed_by}")
        return True

    async def reject(self, chunk_id: str, reviewed_by: str, note: str = "") -> bool:
        """Admin rejects pending content. Soft-delete in Neo4j.

        Returns True if successful, False if not found/not pending.
        """
        async with async_session_maker() as session:
            result = await session.execute(
                select(KnowledgeGovernanceRecord).where(
                    KnowledgeGovernanceRecord.chunk_id == chunk_id,
                    KnowledgeGovernanceRecord.status == "pending_review",
                )
            )
            record = result.scalar_one_or_none()
            if not record:
                logger.warning(f"Cannot reject {chunk_id}: not found or not pending")
                return False

            record.status = "rejected"
            record.reviewed_by = reviewed_by
            record.reviewed_at = datetime.utcnow()
            record.review_note = note
            await session.commit()

        await self._update_neo4j_governance_status(chunk_id, "rejected")
        logger.info(f"Rejected content {chunk_id}")
        logger.debug(f"Rejected by {reviewed_by}")
        return True

    async def revert(self, chunk_id: str, reviewed_by: str, note: str = "") -> bool:
        """Admin reverts medium-risk auto-approved content within revert window.

        Returns True if successful, False if window expired, no revert window, or not found.
        """
        async with async_session_maker() as session:
            result = await session.execute(
                select(KnowledgeGovernanceRecord).where(
                    KnowledgeGovernanceRecord.chunk_id == chunk_id,
                    KnowledgeGovernanceRecord.status == "auto_approved",
                )
            )
            record = result.scalar_one_or_none()
            if not record:
                logger.warning(f"Cannot revert {chunk_id}: not found or not auto_approved")
                return False

            # Only medium-risk items have a revert window; low-risk items cannot be reverted
            if not record.revert_deadline:
                logger.warning(f"Cannot revert {chunk_id}: no revert window (low-risk item)")
                return False

            # Check revert window hasn't expired
            if datetime.utcnow() > record.revert_deadline:
                logger.warning(
                    f"Cannot revert {chunk_id}: revert window expired at {record.revert_deadline}"
                )
                return False

            record.status = "reverted"
            record.reviewed_by = reviewed_by
            record.reviewed_at = datetime.utcnow()
            record.review_note = note
            await session.commit()

        await self._update_neo4j_governance_status(chunk_id, "reverted")
        logger.info(f"Reverted content {chunk_id}")
        logger.debug(f"Reverted by {reviewed_by}")
        return True

    async def get_pending_queue(self) -> list[KnowledgeGovernanceRecord]:
        """Get all pending items for admin review, ordered by submission time."""
        async with async_session_maker() as session:
            result = await session.execute(
                select(KnowledgeGovernanceRecord)
                .where(KnowledgeGovernanceRecord.status == "pending_review")
                .order_by(KnowledgeGovernanceRecord.submitted_at.asc())
            )
            return list(result.scalars().all())

    async def get_revertable_items(self) -> list[KnowledgeGovernanceRecord]:
        """Get auto-approved items still within revert window."""
        now = datetime.utcnow()
        async with async_session_maker() as session:
            result = await session.execute(
                select(KnowledgeGovernanceRecord)
                .where(
                    KnowledgeGovernanceRecord.status == "auto_approved",
                    KnowledgeGovernanceRecord.revert_deadline > now,
                )
                .order_by(KnowledgeGovernanceRecord.submitted_at.asc())
            )
            return list(result.scalars().all())

    async def auto_reject_expired(self) -> int:
        """Auto-reject items pending longer than GOVERNANCE_AUTO_REJECT_DAYS.

        Returns count of auto-rejected items.
        """
        cutoff = datetime.utcnow() - timedelta(days=settings.GOVERNANCE_AUTO_REJECT_DAYS)
        chunk_ids_to_update = []

        # First: update SQLite records and collect chunk_ids
        async with async_session_maker() as session:
            result = await session.execute(
                select(KnowledgeGovernanceRecord).where(
                    KnowledgeGovernanceRecord.status == "pending_review",
                    KnowledgeGovernanceRecord.submitted_at < cutoff,
                )
            )
            expired = list(result.scalars().all())

            for record in expired:
                record.status = "rejected"
                record.reviewed_by = "system"
                record.reviewed_at = datetime.utcnow()
                record.review_note = (
                    f"Auto-rejected after {settings.GOVERNANCE_AUTO_REJECT_DAYS} days"
                )
                chunk_ids_to_update.append(record.chunk_id)

            await session.commit()

        # Then: update Neo4j outside the SQLite session to avoid lock contention
        for chunk_id in chunk_ids_to_update:
            await self._update_neo4j_governance_status(chunk_id, "rejected")

        if expired:
            logger.info(f"Auto-rejected {len(expired)} expired pending items")
        return len(expired)

    # Valid governance status values for Neo4j writes
    _VALID_STATUSES = {"approved", "pending", "rejected", "reverted"}

    async def _update_neo4j_governance_status(self, chunk_id: str, status: str) -> None:
        """Update governance_status in Neo4j episode source_description JSON.

        Uses the same pattern as GraphitiBuilder.update_chunk_metadata():
        read existing source_description -> parse JSON -> update field -> write back.

        Uses graphiti.driver.execute_query() for direct Cypher access.
        """
        if status not in self._VALID_STATUSES:
            logger.error(f"Invalid governance status '{status}' for {chunk_id}, skipping Neo4j update")
            return

        try:
            from knowledge_base.graph.graphiti_client import get_graphiti_client

            client = get_graphiti_client()
            graphiti = await client.get_client()
            driver = graphiti.driver

            # Read current source_description
            records, _, _ = await driver.execute_query(
                """
                MATCH (ep:Episodic {name: $chunk_id})
                WHERE ep.group_id = $group_id
                RETURN ep.source_description AS sd
                LIMIT 1
                """,
                chunk_id=chunk_id,
                group_id=settings.GRAPH_GROUP_ID,
            )

            if not records:
                logger.warning(f"Neo4j episode not found for chunk_id={chunk_id}")
                return

            # Parse, update, serialize
            sd = records[0].get("sd") or "{}"
            metadata = json.loads(sd) if isinstance(sd, str) else sd
            metadata["governance_status"] = status
            updated_sd = json.dumps(metadata, default=str)

            # Write back
            await driver.execute_query(
                """
                MATCH (ep:Episodic {name: $chunk_id})
                WHERE ep.group_id = $group_id
                SET ep.source_description = $source_desc
                """,
                chunk_id=chunk_id,
                group_id=settings.GRAPH_GROUP_ID,
                source_desc=updated_sd,
            )
            logger.debug(f"Updated Neo4j governance_status={status} for {chunk_id}")
        except Exception as e:
            logger.error(
                f"Failed to update Neo4j governance status for {chunk_id}: {e}",
                exc_info=True,
            )
            # Don't raise -- SQLite is the source of truth for governance status.
            # Neo4j update failure is logged but doesn't block the governance workflow.
