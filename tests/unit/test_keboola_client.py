"""Tests for Keboola Storage API client wrapper."""

import csv
import io
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from knowledge_base.keboola.client import KeboolaClient


@pytest.fixture
def client() -> KeboolaClient:
    """Create a KeboolaClient with test credentials."""
    return KeboolaClient(api_url="https://test.keboola.com", api_token="test-token")


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    """Helper to write a CSV file from row dicts."""
    if not rows:
        path.write_text("")
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


class TestGetTableDetail:
    """Tests for get_table_detail()."""

    def test_returns_metadata(self, client: KeboolaClient) -> None:
        mock_tables = MagicMock()
        mock_tables.detail.return_value = {
            "columns": ["text", "metadata", "embedding"],
            "rowsCount": 100,
            "dataSizeBytes": 5000,
        }
        with patch.object(client, "_get_tables_client", return_value=mock_tables):
            result = client.get_table_detail("in.c-bucket.table")

        assert result["columns"] == ["text", "metadata", "embedding"]
        assert result["rowsCount"] == 100
        mock_tables.detail.assert_called_once_with("in.c-bucket.table")


class TestIterTableRows:
    """Tests for iter_table_rows()."""

    def test_streams_rows(self, client: KeboolaClient) -> None:
        """Rows are yielded as dicts with correct column values."""
        sample_rows = [
            {"text": "Hello world", "metadata": "Source-123", "embedding": "[0.1,0.2]"},
            {"text": "Second row", "metadata": "Source-456", "embedding": "[0.3,0.4]"},
        ]

        def fake_export(table_id: str, path_name: str, **kwargs: Any) -> None:
            _write_csv(Path(path_name) / "test-table", sample_rows)

        mock_tables = MagicMock()
        mock_tables.export_to_file.side_effect = fake_export

        with patch.object(client, "_get_tables_client", return_value=mock_tables):
            rows = list(client.iter_table_rows("in.c-bucket.test-table"))

        # embedding should be skipped by default
        assert len(rows) == 2
        assert rows[0]["text"] == "Hello world"
        assert rows[0]["metadata"] == "Source-123"
        assert "embedding" not in rows[0]

    def test_skip_columns(self, client: KeboolaClient) -> None:
        """Custom skip_columns removes specified columns."""
        sample_rows = [
            {"text": "Content", "metadata": "Meta", "extra": "value"},
        ]

        def fake_export(table_id: str, path_name: str, **kwargs: Any) -> None:
            _write_csv(Path(path_name) / "table", sample_rows)

        mock_tables = MagicMock()
        mock_tables.export_to_file.side_effect = fake_export

        with patch.object(client, "_get_tables_client", return_value=mock_tables):
            rows = list(
                client.iter_table_rows("in.c-bucket.table", skip_columns=["metadata", "extra"])
            )

        assert len(rows) == 1
        assert "text" in rows[0]
        assert "metadata" not in rows[0]
        assert "extra" not in rows[0]

    def test_no_skip_columns(self, client: KeboolaClient) -> None:
        """skip_columns=[] returns all columns."""
        sample_rows = [
            {"text": "Content", "metadata": "Meta", "embedding": "[0.1]"},
        ]

        def fake_export(table_id: str, path_name: str, **kwargs: Any) -> None:
            _write_csv(Path(path_name) / "table", sample_rows)

        mock_tables = MagicMock()
        mock_tables.export_to_file.side_effect = fake_export

        with patch.object(client, "_get_tables_client", return_value=mock_tables):
            rows = list(client.iter_table_rows("in.c-bucket.table", skip_columns=[]))

        assert "embedding" in rows[0]
        assert "metadata" in rows[0]

    def test_null_character_stripping(self, client: KeboolaClient) -> None:
        """Null characters in CSV data are stripped."""

        def fake_export(table_id: str, path_name: str, **kwargs: Any) -> None:
            csv_path = Path(path_name) / "table"
            csv_path.write_text("text,metadata\nHello\x00World,Meta\x00data\n")

        mock_tables = MagicMock()
        mock_tables.export_to_file.side_effect = fake_export

        with patch.object(client, "_get_tables_client", return_value=mock_tables):
            rows = list(client.iter_table_rows("in.c-bucket.table", skip_columns=[]))

        assert rows[0]["text"] == "HelloWorld"
        assert rows[0]["metadata"] == "Metadata"

    def test_empty_table(self, client: KeboolaClient) -> None:
        """Empty table yields no rows."""

        def fake_export(table_id: str, path_name: str, **kwargs: Any) -> None:
            csv_path = Path(path_name) / "table"
            csv_path.write_text("text,metadata\n")  # Header only

        mock_tables = MagicMock()
        mock_tables.export_to_file.side_effect = fake_export

        with patch.object(client, "_get_tables_client", return_value=mock_tables):
            rows = list(client.iter_table_rows("in.c-bucket.table", skip_columns=[]))

        assert rows == []

    def test_no_exported_file_raises(self, client: KeboolaClient) -> None:
        """FileNotFoundError when no file is created by export."""

        def fake_export(table_id: str, path_name: str, **kwargs: Any) -> None:
            pass  # Don't create any file

        mock_tables = MagicMock()
        mock_tables.export_to_file.side_effect = fake_export

        with patch.object(client, "_get_tables_client", return_value=mock_tables):
            with pytest.raises(FileNotFoundError, match="No exported file"):
                list(client.iter_table_rows("in.c-bucket.table"))

    def test_changed_since_passed_to_export(self, client: KeboolaClient) -> None:
        """changed_since parameter is forwarded to kbcstorage."""

        def fake_export(table_id: str, path_name: str, **kwargs: Any) -> None:
            _write_csv(Path(path_name) / "table", [{"text": "new", "metadata": "m"}])

        mock_tables = MagicMock()
        mock_tables.export_to_file.side_effect = fake_export

        with patch.object(client, "_get_tables_client", return_value=mock_tables):
            list(
                client.iter_table_rows(
                    "in.c-bucket.table",
                    skip_columns=[],
                    changed_since="2026-01-01T00:00:00",
                )
            )

        mock_tables.export_to_file.assert_called_once_with(
            table_id="in.c-bucket.table",
            path_name=mock_tables.export_to_file.call_args.kwargs.get(
                "path_name",
                mock_tables.export_to_file.call_args[1].get("path_name", ""),
            ),
            changed_since="2026-01-01T00:00:00",
        )

    def test_fallback_file_discovery(self, client: KeboolaClient) -> None:
        """Falls back to first file in directory if expected name not found."""

        def fake_export(table_id: str, path_name: str, **kwargs: Any) -> None:
            _write_csv(Path(path_name) / "unexpected-name.csv", [{"text": "data", "metadata": "m"}])

        mock_tables = MagicMock()
        mock_tables.export_to_file.side_effect = fake_export

        with patch.object(client, "_get_tables_client", return_value=mock_tables):
            rows = list(client.iter_table_rows("in.c-bucket.table", skip_columns=[]))

        assert len(rows) == 1
        assert rows[0]["text"] == "data"
