# Phase 11: Quality Scoring - Test Plan

## Quick Verification

```bash
# Generate some feedback first, then:
python -m knowledge_base.cli scores recalculate

# Check scores
python -m knowledge_base.cli scores stats
```

## Functional Tests

### 1. Score Calculation
```bash
# Calculate and view scores
python -m knowledge_base.cli scores recalculate

sqlite3 knowledge_base.db "
SELECT page_id, quality_score, feedback_score, behavior_score
FROM document_quality
ORDER BY quality_score DESC
LIMIT 10;
"
```

### 2. Feedback Impact
```bash
# Before feedback
python -m knowledge_base.cli scores show page_123

# Add positive feedback
# (via Slack or direct insert)

# After feedback
python -m knowledge_base.cli scores recalculate
python -m knowledge_base.cli scores show page_123

# Score should increase
```

### 3. Freshness Impact
```bash
# Check freshness scores
sqlite3 knowledge_base.db "
SELECT
    page_id,
    freshness_score,
    (julianday('now') - julianday(updated_at)) as age_days
FROM document_quality dq
JOIN raw_pages rp ON dq.page_id = rp.page_id
ORDER BY age_days DESC
LIMIT 10;
"
# Older docs should have lower freshness_score
```

### 4. ChromaDB Update
```bash
# Check ChromaDB has quality_score
python -c "
from knowledge_base.vectorstore.client import ChromaClient
client = ChromaClient()
results = client.collection.get(limit=5, include=['metadatas'])
for meta in results['metadatas']:
    print(f\"{meta.get('page_id')}: quality={meta.get('quality_score')}\")
"
```

### 5. Search Ranking
```bash
# Search should use quality scores
curl -X POST http://localhost:8000/api/v1/search \
  -d '{"query": "common topic"}' | jq '.results[] | {title: .page_title, quality: .metadata.quality_score}'

# Higher quality docs should rank higher
```

## Unit Tests

```python
# tests/test_scoring.py
import pytest
from knowledge_base.feedback.scorer import QualityScorer
from datetime import datetime, timedelta

def test_feedback_score_positive():
    scorer = QualityScorer()
    feedbacks = [
        MockFeedback(feedback_value=1.0),
        MockFeedback(feedback_value=1.0),
        MockFeedback(feedback_value=0.0),
    ]
    score = scorer.calc_feedback_score(feedbacks)
    assert score > 0.5  # More positive than negative

def test_feedback_score_negative():
    scorer = QualityScorer()
    feedbacks = [
        MockFeedback(feedback_value=-1.0),
        MockFeedback(feedback_value=-1.0),
    ]
    score = scorer.calc_feedback_score(feedbacks)
    assert score < 0.5  # Negative

def test_feedback_score_empty():
    scorer = QualityScorer()
    score = scorer.calc_feedback_score([])
    assert score == 0.5  # Neutral default

def test_freshness_new():
    scorer = QualityScorer()
    recent = datetime.utcnow() - timedelta(days=7)
    score = scorer.calc_freshness_score(recent)
    assert score == 1.0

def test_freshness_old():
    scorer = QualityScorer()
    old = datetime.utcnow() - timedelta(days=800)
    score = scorer.calc_freshness_score(old)
    assert score == 0.1

def test_freshness_medium():
    scorer = QualityScorer()
    medium = datetime.utcnow() - timedelta(days=100)
    score = scorer.calc_freshness_score(medium)
    assert 0.5 < score < 1.0

@pytest.mark.asyncio
async def test_calculate_score():
    scorer = QualityScorer()

    # Mock data
    scorer.get_feedbacks_for_page = AsyncMock(return_value=[
        MockFeedback(1.0), MockFeedback(1.0)
    ])
    scorer.get_signals_for_page = AsyncMock(return_value=[])
    scorer.get_usage_stats = AsyncMock(return_value=MockUsage(10, 8))
    scorer.get_page_info = AsyncMock(return_value=MockPage(
        datetime.utcnow() - timedelta(days=30)
    ))

    score = await scorer.calculate_score("page_123")

    assert 0.0 <= score <= 1.0
    assert score > 0.6  # Should be decent with positive feedback
```

## Integration Test

```python
@pytest.mark.asyncio
async def test_scoring_pipeline():
    # Add feedback
    await feedback_collector.record("resp_1", "U123", "thumbs_up", 1.0)
    await feedback_collector.record("resp_2", "U456", "thumbs_up", 1.0)

    # Calculate scores
    scorer = QualityScorer()
    await scorer.recalculate_all()

    # Check score updated
    quality = await get_quality("page_with_feedback")
    assert quality.quality_score > 0.5

    # Check ChromaDB updated
    meta = get_chroma_metadata("chunk_from_page")
    assert "quality_score" in meta
```

## Success Criteria

- [ ] Scores calculated correctly
- [ ] All components weighted properly
- [ ] ChromaDB metadata updated
- [ ] Search uses quality scores
- [ ] Fresh content scored higher
- [ ] Positive feedback increases score
