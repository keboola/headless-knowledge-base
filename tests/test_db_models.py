"""Tests for database models."""

import json
from datetime import datetime, timedelta

import pytest

from knowledge_base.db.models import (
    GovernanceMetadata,
    RawPage,
    calculate_staleness,
)


def test_calculate_staleness_not_stale():
    """Test that recent documents are not flagged as stale."""
    recent_date = datetime.utcnow() - timedelta(days=100)
    is_stale, reason = calculate_staleness(recent_date)
    assert is_stale is False
    assert reason is None


def test_calculate_staleness_stale():
    """Test that old documents are flagged as stale."""
    old_date = datetime.utcnow() - timedelta(days=800)  # > 2 years
    is_stale, reason = calculate_staleness(old_date)
    assert is_stale is True
    assert "Not updated in" in reason
    assert "800" in reason


def test_calculate_staleness_boundary():
    """Test staleness at exactly 2 years."""
    # Just under 2 years
    date_729 = datetime.utcnow() - timedelta(days=729)
    is_stale, _ = calculate_staleness(date_729)
    assert is_stale is False

    # Just over 2 years
    date_731 = datetime.utcnow() - timedelta(days=731)
    is_stale, _ = calculate_staleness(date_731)
    assert is_stale is True


def test_raw_page_repr():
    """Test RawPage string representation."""
    page = RawPage(
        page_id="123",
        space_key="TEST",
        title="A very long title that should be truncated in repr",
        file_path="data/pages/a1b2c3d4e5f6g7h8.md",
        author="test-user",
        url="https://example.com/page",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    repr_str = repr(page)
    assert "123" in repr_str
    assert "A very long title" in repr_str


def test_governance_metadata_repr():
    """Test GovernanceMetadata string representation."""
    gov = GovernanceMetadata(
        page_id="123",
        owner="john.doe",
    )
    repr_str = repr(gov)
    assert "123" in repr_str
    assert "john.doe" in repr_str
