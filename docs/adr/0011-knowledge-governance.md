# ADR-0011: Risk-Based Knowledge Governance

## Status

Proposed (2026-03-07)

## Context

The knowledge base currently has NO authorization for knowledge intake. Anyone in the Slack workspace can create quick facts, ingest external documents, and submit feedback that modifies quality scores. The MCP server has OAuth scopes (`kb.read` / `kb.write`) but the Slack bot has zero access control. This creates a risk of **data pollution** — incorrect, low-quality, or irrelevant content entering the graph and degrading answer quality for all users.

The graph currently holds 196K entities, 400K relationships, and 44K episodes. Protecting this investment requires a governance layer that balances safety with usability.

## Decision

Implement **risk-based knowledge governance** where every knowledge intake gets a risk score (0-100) that determines the approval workflow:

| Tier | Score | Action |
|------|-------|--------|
| **LOW** (0-35) | Auto-approve | Goes live instantly, logged for audit |
| **MEDIUM** (36-65) | Live + review window | Goes live immediately, admin notified in #knowledge-admins, 24h revert window |
| **HIGH** (66-100) | Held pending | NOT searchable until admin explicitly approves in Slack |

## Risk Classification

### Factors (weighted)

| Factor | Weight | How assessed |
|--------|--------|-------------|
| **Author trust** | 25% | Email domain check: `@keboola.com` = low risk, external = high risk |
| **Source type** | 25% | Intake path enum: Confluence sync = low, external URL = high |
| **Content scope** | 15% | Content length + chunk count: single fact = low, multi-chunk doc = high |
| **Novelty** | 20% | Embedding similarity to existing episodes: existing topic = low, new area = high |
| **Contradiction** | 15% | LLM check (only for medium+ base risk): aligns = low, conflicts = high |

### Default Risk by Intake Path

| Path | Base Risk | Rationale |
|------|-----------|-----------|
| Keboola batch import / sync | LOW (10-15) | Trusted source (Confluence via Keboola pipeline) |
| Slack create-knowledge by @keboola.com user | LOW-MEDIUM (30) | Known employee, small scope |
| MCP create_knowledge by @keboola.com user | LOW-MEDIUM (30) | OAuth-verified Keboola employee |
| MCP create_knowledge by external user | HIGH (75) | Unknown trust level |
| Slack/MCP ingest_document (any user) | HIGH (70) | External URL, unknown content quality |
| Feedback corrections | MEDIUM (50) | User-submitted corrections need review |

### Risk Score Calculation

```python
risk_score = (
    author_trust_score * 0.25 +
    source_type_score * 0.25 +
    content_scope_score * 0.15 +
    novelty_score * 0.20 +
    contradiction_score * 0.15
)
```

The contradiction check involves an LLM call and is only triggered when the base risk is MEDIUM or higher (to avoid unnecessary cost for trusted sources).

## Technical Design

### Pending State: Metadata Flag in Neo4j

Add `governance_status` to the `source_description` JSON on each Episodic node:

```json
{
  "governance_status": "approved",
  "governance_risk_tier": "low",
  "governance_risk_score": 25.0,
  "governance_submitted_by": "user@keboola.com",
  "governance_submitted_at": "2026-03-07T12:00:00Z",
  "governance_reviewed_by": null,
  "governance_reviewed_at": null,
  "governance_review_note": "",
  "governance_revert_deadline": null
}
```

**Search-time filtering** in `GraphitiRetriever.search_chunks()`:
```python
governance_status = sr.metadata.get('governance_status', 'approved')
if governance_status not in ('approved',):
    continue
```

Default `'approved'` ensures backward compatibility — existing 196K+ episodes without the field remain searchable.

### Why Not Separate Group ID or SQLite Staging?

**Option A (separate group_id) rejected:** Moving episodes between Graphiti groups requires delete + re-add, which destroys entity relationships built during indexing. Too fragile.

**Option C (SQLite staging) rejected:** Violates the principle that Neo4j is the source of truth. Would also require deferring Graphiti entity extraction until approval, creating poor UX where admin approves but content takes 30+ seconds to become searchable (waiting for 7-20 LLM calls).

**Option B (metadata flag) chosen:** Content is indexed to Graphiti immediately (entities extracted, relationships built), but filtered at search time. On approval, a single Neo4j property update makes it searchable. On rejection, a soft-delete marks it as removed. Zero re-indexing needed.

### SQLite Audit Table

`knowledge_governance` table for fast admin queries and audit trail:

| Column | Type | Purpose |
|--------|------|---------|
| chunk_id | string | Matches Neo4j episode |
| risk_score | float | 0-100 |
| risk_tier | string | low / medium / high |
| intake_path | string | mcp_create / slack_ingest / keboola_sync / etc. |
| submitted_by | string | Email or Slack user ID |
| status | string | auto_approved / pending_review / approved / rejected / reverted |
| reviewed_by | string | Admin who reviewed |
| reviewed_at | datetime | When reviewed |
| review_note | string | Admin's note |
| revert_deadline | datetime | For medium-risk: end of 24h window |
| slack_notification_ts | string | Tracks the Slack message for button updates |

### Admin Slack Interface

**HIGH risk — Approval request:**
```
Knowledge Approval Request

Submitted by: user@external.com (via MCP ingest_document)
Risk: HIGH (score: 78/100)
Risk factors:
  - Author: External user (75)
  - Source: External URL (80)
  - Scope: 12 chunks, 8500 chars (60)
  - Novelty: New topic area (70)

Content preview:
> First 300 characters of content...

Source URL: https://example.com/article
Chunks: 12 pending

[Approve] [Reject] [View Full Content]
```

**MEDIUM risk — Auto-approved with revert:**
```
Knowledge Auto-Approved (Review Window: 24h)

Submitted by: @jiri.manas (via /create-knowledge)
Risk: MEDIUM (score: 42/100)
Content:
> The new deployment process requires...

Status: Live now. Revert available until Mar 8, 12:00 UTC.

[Revert] [Mark Reviewed]
```

**`/governance-queue` command:**
```
Pending Knowledge Approvals (3 items)

1. "Quick Fact by external_user" (HIGH, score 78)
   Submitted 2h ago via MCP | [Approve] [Reject]

2. "Web scrape: Best Practices Guide" (HIGH, score 72)
   Submitted 5h ago via /ingest-doc, 8 chunks | [Approve] [Reject]

3. "Process update" (MEDIUM, under review)
   Auto-approved 18h ago, revert deadline in 6h | [Revert] [OK]
```

### Configuration

```python
# Knowledge Governance (all configurable via env vars)
GOVERNANCE_ENABLED: bool = False            # Feature flag for gradual rollout
GOVERNANCE_LOW_RISK_THRESHOLD: int = 35     # Score 0-35 = auto-approve
GOVERNANCE_HIGH_RISK_THRESHOLD: int = 66    # Score 66-100 = require approval
GOVERNANCE_TRUSTED_DOMAINS: str = "keboola.com"  # Comma-separated trusted email domains
GOVERNANCE_REVERT_WINDOW_HOURS: int = 24    # Hours before medium-risk revert window closes
GOVERNANCE_AUTO_REJECT_DAYS: int = 14       # Days before pending items are auto-rejected
GOVERNANCE_CONTRADICTION_CHECK_ENABLED: bool = True  # Enable LLM contradiction detection
GOVERNANCE_NOVELTY_SIMILARITY_THRESHOLD: float = 0.7 # Cosine sim threshold for "existing topic"
```

## Implementation Plan

| Phase | Scope | Effort |
|-------|-------|--------|
| 1. Core + feature flag | RiskClassifier, config, SQLite model, search filter | 3-4 days |
| 2. Admin Slack UI | Approval/reject/revert handlers, `/governance-queue` | 3-4 days |
| 3. Intake path gates | Wire governance into MCP tools, Slack commands, Keboola sync | 2-3 days |
| 4. Tests + staging | Unit tests, e2e tests, staging deploy with `GOVERNANCE_ENABLED=true` | 2-3 days |
| 5. Production rollout | Conservative thresholds, monitor admin channel volume, tune | 1-2 days |
| **Total** | | **~12-16 days** |

### New Files

| File | Purpose |
|------|---------|
| `src/knowledge_base/governance/__init__.py` | Package init |
| `src/knowledge_base/governance/risk_classifier.py` | Risk scoring logic |
| `src/knowledge_base/governance/approval_engine.py` | Neo4j status updates (approve/reject/revert) |
| `src/knowledge_base/slack/governance_admin.py` | Slack button handlers, `/governance-queue` |
| `tests/unit/test_risk_classifier.py` | Risk classification tests |
| `tests/unit/test_governance_admin.py` | Admin UI tests |
| `tests/unit/test_approval_engine.py` | Approval engine tests |

### Modified Files

| File | Change |
|------|--------|
| `src/knowledge_base/config.py` | Add governance settings |
| `src/knowledge_base/db/models.py` | Add `KnowledgeGovernanceRecord` model |
| `src/knowledge_base/graph/graphiti_retriever.py` | Add governance_status filter in search |
| `src/knowledge_base/mcp/tools.py` | Wire governance into create/ingest tools |
| `src/knowledge_base/slack/bot.py` | Register governance handlers |
| `src/knowledge_base/vectorstore/indexer.py` | Add governance fields to ChunkData |

## Migration

Feature-flagged with `GOVERNANCE_ENABLED=false` by default. All existing 196K+ episodes lack `governance_status` in their metadata — the search filter defaults to `'approved'` for missing fields, ensuring zero impact on existing content.

Production rollout starts with conservative thresholds (LOW < 25, HIGH > 75) and is adjusted based on the ratio of false positives (legitimate content held for review) to true positives (actual pollution caught).

## Consequences

### Positive
- Prevents data pollution from untrusted sources
- Admins can govern knowledge via familiar Slack interface
- Trusted sources (Confluence, Keboola employees) experience zero friction
- Full audit trail for compliance
- Feature-flagged for safe rollout

### Negative
- External users experience delay (content held until admin approval)
- Admin burden for reviewing HIGH-risk submissions (mitigated by risk tuning)
- One additional LLM call per medium/high-risk submission (contradiction check)
- Complexity increase in intake paths (6 modified files)

### Neutral
- No impact on search performance (single metadata field check per result, negligible)
- No impact on existing content (backward compatible defaults)
