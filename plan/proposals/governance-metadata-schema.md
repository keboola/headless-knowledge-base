# Proposal: Fixed Governance Metadata Schema

## Summary

Add structured governance metadata (separate from AI-generated content metadata) to track document ownership, review cycles, compliance, and lifecycle.

## Proposed Schema

```python
class GovernanceMetadata(Base):
    __tablename__ = "governance_metadata"

    page_id: str                    # FK to raw_pages

    # === OWNERSHIP ===
    document_owner: str | None      # Accountable person (from Confluence or labels)
    owner_department: str | None    # Owner's department
    author: str                     # Original creator (from Confluence)

    # === REVIEW CYCLE ===
    last_reviewed_at: datetime | None   # Last review date
    reviewed_by: str | None             # Who reviewed
    review_frequency_days: int | None   # e.g., 365 = annual review
    next_review_due: datetime | None    # Calculated: last_reviewed + frequency

    # === COMPLIANCE ===
    sensitivity_level: str          # "public", "internal", "confidential", "restricted"
    regulatory_tags: list[str]      # ["GDPR", "SOC2", "internal-only"]
    retention_period_days: int | None   # How long to keep
    legal_hold: bool                # Cannot delete if True

    # === LIFECYCLE ===
    status: str                     # "draft", "approved", "superseded", "archived"
    effective_date: datetime | None # When doc becomes active
    expiration_date: datetime | None    # When doc expires (triggers review)

    # === VERSION ===
    version: str | None             # "1.0", "2.1" etc
    supersedes_page_id: str | None  # Previous version
    superseded_by_page_id: str | None   # Newer version (auto-set)

    # === TRACKING ===
    created_at: datetime            # Record creation
    updated_at: datetime            # Record update
```

## Data Sources

| Field | Source | Auto/Manual |
|-------|--------|-------------|
| author | Confluence API | Auto |
| document_owner | Confluence labels (`owner:name`) or page property | Auto-extract |
| sensitivity_level | Confluence labels (`sensitivity:internal`) | Auto-extract |
| regulatory_tags | Confluence labels (`compliance:gdpr`) | Auto-extract |
| last_reviewed_at | Confluence page version history | Auto (if convention used) |
| review_frequency_days | Confluence labels (`review-cycle:365`) | Auto-extract |
| status | Confluence page status or labels | Auto |
| version | Confluence version or labels | Auto |

## Label Convention (for Confluence)

```
owner:john.doe
sensitivity:confidential
compliance:gdpr
compliance:soc2
review-cycle:365
legal-hold:true
```

## Integration Points

1. **Phase 02**: Extract governance labels during download
2. **Phase 11**: Factor governance into quality scoring (stale reviews = lower score)
3. **Phase 12**: Use for governance reports (overdue reviews, missing owners)

## Benefits

- Clear accountability (who owns what)
- Compliance visibility (what's sensitive, what regulations apply)
- Proactive review tracking (don't wait for content to go stale)
- Audit trail (when reviewed, by whom)

## Minimal Start (3 fields)

If full schema is too much, start with:
1. `document_owner` - who's responsible
2. `last_reviewed_at` - when last checked
3. `sensitivity_level` - how sensitive

---

**Approve?** Yes / No / Modify
