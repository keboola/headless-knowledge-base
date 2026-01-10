"""Convert Confluence HTML to Markdown."""

import logging
import re
import secrets
import sys
from contextlib import contextmanager
from pathlib import Path

from bs4 import BeautifulSoup, Tag
from markdownify import markdownify as md

from knowledge_base.config import settings

logger = logging.getLogger(__name__)

# Maximum HTML nesting depth before flattening (safe margin below recursion limit)
MAX_NESTING_DEPTH = 100


@contextmanager
def _increased_recursion_limit(limit: int = 2000):
    """Temporarily increase Python's recursion limit."""
    old_limit = sys.getrecursionlimit()
    sys.setrecursionlimit(max(old_limit, limit))
    try:
        yield
    finally:
        sys.setrecursionlimit(old_limit)


def _limit_html_depth(html: str, max_depth: int = MAX_NESTING_DEPTH) -> str:
    """
    Flatten HTML that exceeds max nesting depth.

    Also detects and breaks cyclical DOM references (e.g., from malformed HTML
    where an element becomes its own ancestor).

    Args:
        html: Raw HTML string
        max_depth: Maximum allowed nesting depth

    Returns:
        HTML string with deep nesting flattened to text
    """
    soup = BeautifulSoup(html, "html.parser")
    seen_ids: set[int] = set()  # For cycle detection using object ids

    def flatten_deep_nodes(element, current_depth: int = 0) -> None:
        if not isinstance(element, Tag):
            return

        for child in list(element.children):
            # Cycle detection using Python object id
            child_id = id(child)
            if child_id in seen_ids:
                # Break cycle by removing the node
                if hasattr(child, "decompose"):
                    child.decompose()
                continue
            seen_ids.add(child_id)

            if current_depth >= max_depth:
                # Extract text content, remove nested structure
                if hasattr(child, "get_text"):
                    text = child.get_text(separator=" ", strip=True)
                    child.replace_with(text)
            else:
                flatten_deep_nodes(child, current_depth + 1)

    flatten_deep_nodes(soup)
    return str(soup)


def html_to_markdown(html_content: str) -> str:
    """
    Convert Confluence HTML to clean Markdown with 3-layer recursion protection.

    Uses a defense-in-depth strategy:
    1. Limit HTML nesting depth before conversion (prevents most recursion issues)
    2. Temporarily increase Python recursion limit (buffer for edge cases)
    3. Graceful fallback to plain text if conversion still fails

    Args:
        html_content: Raw HTML from Confluence

    Returns:
        Clean Markdown string (or plain text fallback if conversion fails)
    """
    # Clean up Confluence-specific markup first
    html_content = _clean_confluence_html(html_content)

    try:
        # Layer 1: Limit nesting depth and break any cycles
        safe_html = _limit_html_depth(html_content)

        # Layer 2: Temporarily increase recursion limit for edge cases
        with _increased_recursion_limit(2000):
            markdown = md(
                safe_html,
                heading_style="ATX",
                bullets="-",
                code_language_callback=_detect_code_language,
            )

        # Clean up the markdown
        return _clean_markdown(markdown)

    except RecursionError as e:
        # Layer 3: Fallback to plain text extraction
        logger.warning(f"Markdown conversion failed due to deep nesting: {e}")
        soup = BeautifulSoup(html_content, "html.parser")
        plain_text = soup.get_text(separator="\n\n", strip=True)
        return f"[Content extracted as plain text due to complex formatting]\n\n{plain_text}"


def _clean_confluence_html(html: str) -> str:
    """Remove Confluence-specific elements."""
    # Remove ac: and ri: namespace elements
    html = re.sub(r"<ac:[^>]*>.*?</ac:[^>]*>", "", html, flags=re.DOTALL)
    html = re.sub(r"<ri:[^>]*/>", "", html)
    html = re.sub(r"<ri:[^>]*>.*?</ri:[^>]*>", "", html, flags=re.DOTALL)

    # Remove empty tags
    html = re.sub(r"<[^>]+>\s*</[^>]+>", "", html)

    return html


def _detect_code_language(el) -> str | None:
    """Detect code language from element attributes."""
    if el.get("class"):
        classes = el.get("class", [])
        for cls in classes:
            if cls.startswith("language-"):
                return cls.replace("language-", "")
    return None


def _clean_markdown(markdown: str) -> str:
    """Clean up generated markdown."""
    # Remove excessive blank lines (more than 2)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)

    # Remove trailing whitespace from lines
    lines = [line.rstrip() for line in markdown.split("\n")]
    markdown = "\n".join(lines)

    # Strip leading/trailing whitespace
    markdown = markdown.strip()

    return markdown


def generate_random_filename() -> str:
    """Generate a random 16-character hex filename."""
    return secrets.token_hex(8)  # 8 bytes = 16 hex chars


def get_pages_dir() -> Path:
    """Get the pages directory, creating it if needed."""
    pages_dir = Path(settings.PAGES_DIR)
    pages_dir.mkdir(parents=True, exist_ok=True)
    return pages_dir


def save_markdown_file(markdown_content: str, filename: str | None = None) -> str:
    """
    Save markdown content to a file with random name.

    Args:
        markdown_content: The markdown content to save
        filename: Optional filename (without extension). If not provided, generates random name.

    Returns:
        The file path relative to current directory
    """
    pages_dir = get_pages_dir()

    if filename is None:
        filename = generate_random_filename()

    file_path = pages_dir / f"{filename}.md"
    file_path.write_text(markdown_content, encoding="utf-8")

    return str(file_path)


def read_markdown_file(file_path: str) -> str:
    """
    Read markdown content from a file.

    Args:
        file_path: Path to the markdown file

    Returns:
        The markdown content
    """
    return Path(file_path).read_text(encoding="utf-8")


def delete_markdown_file(file_path: str) -> bool:
    """
    Delete a markdown file.

    Args:
        file_path: Path to the markdown file

    Returns:
        True if deleted, False if file didn't exist
    """
    path = Path(file_path)
    if path.exists():
        path.unlink()
        return True
    return False
