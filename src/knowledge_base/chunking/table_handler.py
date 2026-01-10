"""Handler for converting HTML tables to markdown."""

from dataclasses import dataclass

from bs4 import Tag


@dataclass
class TableChunk:
    """A chunk containing table data."""

    content: str
    row_count: int
    col_count: int
    is_complete: bool = True  # False if table was split


class TableHandler:
    """Converts HTML tables to markdown format."""

    MAX_ROWS_INTACT = 20  # Keep tables smaller than this as single chunk

    def process(self, table: Tag) -> list[TableChunk]:
        """
        Convert an HTML table to markdown chunks.

        Small tables (<20 rows): Keep as single markdown chunk
        Large tables: Split into row-by-row chunks with header context
        """
        rows = table.find_all("tr")
        if not rows:
            return []

        # Extract headers
        headers = self._extract_headers(rows[0])
        data_rows = rows[1:] if headers else rows

        # Determine strategy
        if len(data_rows) <= self.MAX_ROWS_INTACT:
            return [self._table_to_single_chunk(headers, data_rows)]
        else:
            return self._split_large_table(headers, data_rows)

    def _extract_headers(self, first_row: Tag) -> list[str]:
        """Extract header text from the first row."""
        headers = []
        for cell in first_row.find_all(["th", "td"]):
            text = cell.get_text(strip=True)
            headers.append(text)

        # Check if this looks like a header row
        th_count = len(first_row.find_all("th"))
        if th_count > 0:
            return headers

        return []

    def _table_to_single_chunk(
        self, headers: list[str], data_rows: list[Tag]
    ) -> TableChunk:
        """Convert entire table to a single markdown chunk."""
        lines = []

        if headers:
            lines.append("| " + " | ".join(headers) + " |")
            lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

        for row in data_rows:
            cells = [cell.get_text(strip=True) for cell in row.find_all(["td", "th"])]
            if cells:
                # Escape pipe characters in cell content
                cells = [c.replace("|", "\\|") for c in cells]
                lines.append("| " + " | ".join(cells) + " |")

        content = "\n".join(lines)
        return TableChunk(
            content=content,
            row_count=len(data_rows),
            col_count=len(headers) if headers else self._get_col_count(data_rows),
            is_complete=True,
        )

    def _split_large_table(
        self, headers: list[str], data_rows: list[Tag]
    ) -> list[TableChunk]:
        """Split a large table into multiple chunks with header context."""
        chunks = []
        chunk_size = 10  # Rows per chunk

        for i in range(0, len(data_rows), chunk_size):
            chunk_rows = data_rows[i : i + chunk_size]
            lines = []

            # Always include headers in each chunk
            if headers:
                lines.append("| " + " | ".join(headers) + " |")
                lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

            for row in chunk_rows:
                cells = [cell.get_text(strip=True) for cell in row.find_all(["td", "th"])]
                if cells:
                    cells = [c.replace("|", "\\|") for c in cells]
                    lines.append("| " + " | ".join(cells) + " |")

            # Add context about position in table
            position_note = f"\n(Rows {i + 1}-{i + len(chunk_rows)} of {len(data_rows)})"
            lines.append(position_note)

            content = "\n".join(lines)
            chunks.append(
                TableChunk(
                    content=content,
                    row_count=len(chunk_rows),
                    col_count=len(headers) if headers else self._get_col_count(chunk_rows),
                    is_complete=False,
                )
            )

        return chunks

    def _get_col_count(self, rows: list[Tag]) -> int:
        """Get column count from data rows."""
        if not rows:
            return 0
        first_row = rows[0]
        return len(first_row.find_all(["td", "th"]))


def is_table_element(element: Tag) -> bool:
    """Check if an element is a table."""
    return element.name == "table"
