"""Keboola Storage downloader -- fetches pre-chunked data and maps to ChunkData.

Downloads table data from Keboola Storage API, parses the metadata string,
and converts rows to ChunkData format for GraphitiIndexer.
"""

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from knowledge_base.config import settings
from knowledge_base.keboola.client import KeboolaClient
from knowledge_base.vectorstore.indexer import ChunkData

logger = logging.getLogger(__name__)


class KeboolaDownloader:
    """Downloads table data from Keboola Storage and converts to ChunkData.

    The data is expected to be pre-chunked. This downloader:
    1. Fetches table rows via Keboola Storage API
    2. Parses the metadata string to extract source and page_id
    3. Maps columns to ChunkData fields
    4. Returns list[ChunkData] ready for GraphitiIndexer
    """

    def __init__(
        self,
        client: KeboolaClient | None = None,
        source_key: str | None = None,
    ):
        self.client = client or KeboolaClient()
        self.source_key = source_key or settings.KEBOOLA_SOURCE_KEY

    @staticmethod
    def _parse_metadata(metadata_str: str) -> tuple[str, str]:
        """Parse Keboola metadata string into (source_name, page_id).

        Expected format: "Confluence - Engineering Wiki-3218833620"
        -> source_name = "Engineering Wiki", page_id = "3218833620"

        Falls back gracefully for unexpected formats.
        """
        if not metadata_str:
            return "", ""

        # Split on " - " to separate source type from the rest
        parts = metadata_str.split(" - ", maxsplit=1)
        if len(parts) < 2:
            return metadata_str.strip(), ""

        remainder = parts[1].strip()

        # The last "-" separated segment is the page_id (numeric)
        last_dash = remainder.rfind("-")
        if last_dash == -1:
            return remainder, ""

        page_id_candidate = remainder[last_dash + 1 :].strip()
        source_name = remainder[:last_dash].strip()

        return source_name, page_id_candidate

    def _map_row_to_chunk(
        self,
        row: dict[str, str],
        row_index: int,
        table_id: str,
        page_chunk_counters: dict[str, int],
    ) -> ChunkData | None:
        """Map a single Keboola row to a ChunkData object.

        Returns None if the row has no usable content.
        """
        content = row.get("text", "").strip()
        if not content:
            return None

        metadata_str = row.get("metadata", "")
        source_name, page_id = self._parse_metadata(metadata_str)

        if not page_id:
            page_id = f"kbc_row_{row_index}"

        # Track chunk index per page_id for proper ordering
        chunk_index = page_chunk_counters[page_id]
        page_chunk_counters[page_id] += 1

        # Generate unique chunk_id
        table_short = table_id.split(".")[-1] if "." in table_id else table_id
        chunk_id = f"kbc_{table_short}_{page_id}_{chunk_index}"

        page_title = source_name or f"Keboola Import {row_index}"
        space_key = self.source_key

        return ChunkData(
            chunk_id=chunk_id,
            content=content,
            page_id=page_id,
            page_title=page_title,
            chunk_index=chunk_index,
            space_key=space_key,
            url="",
            author="",
            created_at="",
            updated_at="",
            chunk_type="text",
            parent_headers="[]",
            doc_type="keboola_import",
            summary=content[:200] if len(content) > 200 else content,
        )

    def fetch_chunks(
        self,
        table_id: str | None = None,
        changed_since: str | None = None,
    ) -> list[ChunkData]:
        """Fetch table data and map to ChunkData objects.

        Args:
            table_id: Keboola table ID (defaults to settings.KEBOOLA_TABLE_ID).
            changed_since: ISO timestamp for incremental export.

        Returns:
            List of ChunkData objects ready for indexing.
        """
        table_id = table_id or settings.KEBOOLA_TABLE_ID

        chunks: list[ChunkData] = []
        skipped = 0
        page_chunk_counters: dict[str, int] = defaultdict(int)

        for idx, row in enumerate(
            self.client.iter_table_rows(
                table_id,
                changed_since=changed_since,
            )
        ):
            chunk_data = self._map_row_to_chunk(row, idx, table_id, page_chunk_counters)
            if chunk_data is None:
                skipped += 1
                continue
            chunks.append(chunk_data)

            if (idx + 1) % 5000 == 0:
                logger.info("Mapped %d rows so far (%d skipped)...", idx + 1, skipped)

        logger.info(
            "Mapped %d chunks from %d rows (skipped %d empty/invalid)",
            len(chunks),
            len(chunks) + skipped,
            skipped,
        )
        return chunks

    def get_table_info(self, table_id: str | None = None) -> dict[str, Any]:
        """Get table metadata for diagnostics."""
        table_id = table_id or settings.KEBOOLA_TABLE_ID
        return self.client.get_table_detail(table_id)

    async def get_last_sync_time(self, table_id: str) -> datetime | None:
        """Read last successful sync timestamp from KeboolaSyncState."""
        from knowledge_base.db.database import async_session_maker
        from knowledge_base.db.models import KeboolaSyncState
        from sqlalchemy import select

        async with async_session_maker() as session:
            result = await session.execute(
                select(KeboolaSyncState).where(
                    KeboolaSyncState.source_id == table_id
                )
            )
            state = result.scalar_one_or_none()
            if state and state.last_sync_at:
                return state.last_sync_at
        return None

    async def save_sync_state(
        self,
        table_id: str,
        rows_synced: int,
        status: str = "success",
    ) -> None:
        """Save sync state after a completed run."""
        from knowledge_base.db.database import async_session_maker
        from knowledge_base.db.models import KeboolaSyncState
        from sqlalchemy import select

        now = datetime.now(timezone.utc)

        async with async_session_maker() as session:
            result = await session.execute(
                select(KeboolaSyncState).where(
                    KeboolaSyncState.source_id == table_id
                )
            )
            state = result.scalar_one_or_none()

            if state:
                state.last_sync_at = now
                state.rows_synced = rows_synced
                state.status = status
            else:
                state = KeboolaSyncState(
                    source_id=table_id,
                    last_sync_at=now,
                    rows_synced=rows_synced,
                    status=status,
                )
                session.add(state)

            await session.commit()
            logger.info(
                "Saved sync state for %s: %d rows, status=%s",
                table_id,
                rows_synced,
                status,
            )
