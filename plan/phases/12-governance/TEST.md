# Phase 12: Governance Reports - Test Plan

## Quick Verification

```bash
# Generate governance report
python -m knowledge_base.cli governance report

# Should list:
# - Obsolete documents
# - Documentation gaps
# - Low quality content
```

## Functional Tests

### 1. Obsolete Detection
```bash
curl http://localhost:8000/api/v1/governance/obsolete | jq

# Expected format:
# [
#   {
#     "page_id": "123",
#     "title": "Old Policy",
#     "last_updated": "2022-01-15",
#     "reasons": ["Not updated in 800 days", "Low quality score: 0.25"]
#   }
# ]
```

### 2. Gap Analysis
```bash
curl http://localhost:8000/api/v1/governance/gaps | jq

# Expected format:
# [
#   {
#     "topic": "expense reporting",
#     "query_count": 15,
#     "sample_queries": ["How do I submit expenses?", ...],
#     "suggested_title": "Expense Reporting Guide"
#   }
# ]
```

### 3. Coverage Matrix
```bash
curl http://localhost:8000/api/v1/governance/coverage | jq

# Expected format:
# {
#   "onboarding": {"doc_count": 5, "avg_quality": 0.8, "query_count": 50},
#   "benefits": {"doc_count": 3, "avg_quality": 0.6, "query_count": 100},
#   ...
# }
```

### 4. Low Quality Docs
```bash
curl http://localhost:8000/api/v1/governance/low-quality | jq '.[] | {title, quality_score}'

# Should list docs with quality_score < 0.4
```

### 5. CLI Export
```bash
python -m knowledge_base.cli governance export --format=csv -o governance_report.csv
cat governance_report.csv
```

## Unit Tests

```python
# tests/test_governance.py
import pytest
from datetime import datetime, timedelta
from knowledge_base.governance.obsolete_detector import ObsoleteDetector
from knowledge_base.governance.gap_analyzer import GapAnalyzer

@pytest.mark.asyncio
async def test_detect_old_document():
    detector = ObsoleteDetector(max_age_days=365)

    # Mock old page
    old_page = MockPage(
        id="old_1",
        updated_at=datetime.utcnow() - timedelta(days=400)
    )

    result = await detector.check_page(old_page)
    assert result.is_obsolete
    assert "Not updated" in result.reasons[0]

@pytest.mark.asyncio
async def test_detect_low_quality():
    detector = ObsoleteDetector(min_quality=0.3)

    # Mock low quality page
    page = MockPage(id="low_1", updated_at=datetime.utcnow())

    # Mock quality score
    detector.get_quality_score = AsyncMock(return_value=0.2)

    result = await detector.check_page(page)
    assert result.is_obsolete
    assert "Low quality" in str(result.reasons)

def test_cluster_similar_queries():
    analyzer = GapAnalyzer()

    queries = [
        "How do I submit expenses?",
        "How to submit expense report?",
        "Expense submission process",
        "What is the vacation policy?",  # Different topic
    ]

    clusters = analyzer.cluster_queries_simple(queries)

    # Should have 2 clusters
    assert len(clusters) == 2

    # Expense queries should be together
    expense_cluster = next(c for c in clusters if "expense" in c.queries[0].lower())
    assert len(expense_cluster.queries) == 3

@pytest.mark.asyncio
async def test_gap_identification():
    analyzer = GapAnalyzer()

    # Mock failed queries
    failed = [
        "expense report", "expense report", "expense report",
        "expense submission", "submit expenses"
    ]

    analyzer.get_failed_queries = AsyncMock(return_value=failed)

    gaps = await analyzer.find_gaps()

    assert len(gaps) >= 1
    assert gaps[0].query_count >= 3
```

## Integration Test

```python
@pytest.mark.asyncio
async def test_full_governance_report():
    # Setup: Create old doc and failed queries
    await create_page(
        id="old_doc",
        updated_at=datetime.utcnow() - timedelta(days=800)
    )

    for _ in range(5):
        await log_failed_query("How to do expense reports?")

    # Run governance checks
    detector = ObsoleteDetector()
    obsolete = await detector.find_obsolete()

    analyzer = GapAnalyzer()
    gaps = await analyzer.find_gaps()

    # Verify
    assert any(d.page_id == "old_doc" for d in obsolete)
    assert any("expense" in g.topic.lower() for g in gaps)
```

## Success Criteria

- [ ] Old documents flagged correctly
- [ ] Low quality docs identified
- [ ] Query clusters make sense
- [ ] Gaps prioritized by frequency
- [ ] Coverage matrix accurate
- [ ] Reports exportable
