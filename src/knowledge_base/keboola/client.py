"""Keboola Storage API client wrapper.

Wraps the synchronous kbcstorage library to provide streaming table data
for the knowledge base pipeline.
"""

import csv
import logging
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from knowledge_base.config import settings

logger = logging.getLogger(__name__)


class KeboolaClient:
    """Client for fetching data from Keboola Storage API.

    Uses kbcstorage library to export table data as CSV
    and provides row iteration via generator.
    """

    def __init__(
        self,
        api_url: str | None = None,
        api_token: str | None = None,
    ):
        self.api_url = api_url or settings.KEBOOLA_API_URL
        self.api_token = api_token or settings.KEBOOLA_API_TOKEN

        if not self.api_url:
            raise ValueError("Keboola API URL must not be empty. Set KEBOOLA_API_URL.")
        if not self.api_token:
            raise ValueError("Keboola API token must not be empty. Set KEBOOLA_API_TOKEN.")

    def _get_tables_client(self) -> Any:
        """Lazy-load kbcstorage Tables client."""
        from kbcstorage.tables import Tables

        return Tables(self.api_url, self.api_token)

    def get_table_detail(self, table_id: str) -> dict[str, Any]:
        """Get table metadata (columns, row count, etc.)."""
        tables = self._get_tables_client()
        return tables.detail(table_id)

    def iter_table_rows(
        self,
        table_id: str,
        skip_columns: list[str] | None = None,
        changed_since: str | None = None,
    ) -> Iterator[dict[str, str]]:
        """Export table data and yield rows as dicts.

        Streams rows from a temp CSV file to avoid loading the entire
        table into memory (can be 1.5GB+).

        Args:
            table_id: Full Keboola table ID.
            skip_columns: Columns to exclude from output (default: ["embedding"]).
            changed_since: ISO timestamp for incremental export. Only rows
                modified after this timestamp are returned.

        Yields:
            Row dicts keyed by column name.
        """
        if skip_columns is None:
            skip_columns = ["embedding"]

        tables = self._get_tables_client()

        with tempfile.TemporaryDirectory() as tmpdir:
            export_kwargs: dict[str, Any] = {
                "table_id": table_id,
                "path_name": tmpdir,
            }
            if changed_since:
                export_kwargs["changed_since"] = changed_since

            logger.info(
                "Exporting table %s (changed_since=%s)",
                table_id,
                changed_since or "full",
            )
            tables.export_to_file(**export_kwargs)

            # kbcstorage saves as table name (last part of table_id)
            table_name = table_id.split(".")[-1]
            csv_path = Path(tmpdir) / table_name

            if not csv_path.exists():
                # Fallback: find the first file in temp dir
                files = list(Path(tmpdir).iterdir())
                if not files:
                    raise FileNotFoundError(
                        f"No exported file found for table {table_id}"
                    )
                csv_path = files[0]

            file_size = csv_path.stat().st_size
            logger.info("Exported file: %s (%d bytes)", csv_path.name, file_size)

            row_count = 0
            with open(csv_path, mode="rt", encoding="utf-8") as f:
                # Strip null characters per kbcstorage docs
                clean_lines = (line.replace("\0", "") for line in f)
                reader = csv.DictReader(clean_lines)

                for row in reader:
                    # Remove skipped columns
                    for col in skip_columns:
                        row.pop(col, None)
                    row_count += 1
                    yield row

            logger.info("Streamed %d rows from table %s", row_count, table_id)
