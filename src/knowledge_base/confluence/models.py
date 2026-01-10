"""Data models for Confluence API responses."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Permission:
    """Confluence page permission."""

    type: str  # "user" or "group"
    name: str  # username or group name
    operation: str  # "read", "edit", etc.


@dataclass
class Attachment:
    """Confluence page attachment."""

    id: str
    title: str
    media_type: str
    file_size: int
    download_url: str


@dataclass
class Page:
    """Basic page metadata from Confluence list API."""

    id: str
    title: str
    space_key: str
    url: str
    status: str
    created_at: datetime
    updated_at: datetime
    author: str  # Account ID
    author_name: str = ""  # Display name
    version_number: int = 1
    parent_id: str | None = None


@dataclass
class PageContent:
    """Full page content including body and metadata."""

    id: str
    title: str
    space_key: str
    url: str
    html_content: str
    author: str  # Account ID
    author_name: str  # Display name
    parent_id: str | None
    created_at: datetime
    updated_at: datetime
    version_number: int
    status: str
    labels: list[str] = field(default_factory=list)
    permissions: list[Permission] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)


@dataclass
class GovernanceInfo:
    """Governance information extracted from Confluence labels."""

    owner: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    classification: str = "internal"
    doc_type: str | None = None

    @classmethod
    def from_labels(cls, labels: list[str]) -> "GovernanceInfo":
        """Extract governance fields from Confluence labels."""
        governance = cls()
        for label in labels:
            label_lower = label.lower()
            if label_lower.startswith("owner:"):
                governance.owner = label.split(":", 1)[1].strip()
            elif label_lower.startswith("reviewed-by:"):
                governance.reviewed_by = label.split(":", 1)[1].strip()
            elif label_lower.startswith("reviewed:"):
                try:
                    date_str = label.split(":", 1)[1].strip()
                    governance.reviewed_at = datetime.fromisoformat(date_str)
                except (ValueError, IndexError):
                    pass
            elif label_lower in ("public", "internal", "confidential"):
                governance.classification = label_lower
            elif label_lower in ("policy", "procedure", "guideline", "general"):
                governance.doc_type = label_lower
        return governance
