# Phase 11: Quality Scoring

## Overview

Calculate and update document quality scores based on accumulated feedback, for search ranking.

## Dependencies

- **Requires**: Phase 10 (Feedback), Phase 10.5 (Behavioral Signals)
- **Blocks**: Phase 12 (Governance)
- **Parallel**: Phase 11.5 (Nightly Evaluation)

## Deliverables

```
src/knowledge_base/
├── feedback/
│   └── scorer.py             # Quality score calculation
├── tasks/
│   └── scoring_tasks.py      # Celery tasks for scoring
```

## Technical Specification

### Quality Score Model

Quality score per document combines multiple signals:

```python
class DocumentQuality:
    page_id: str
    quality_score: float          # 0.0 - 1.0 (weighted average)
    relevance_score: float        # How often useful in answers
    feedback_score: float         # Explicit feedback average
    behavior_score: float         # Implicit behavioral signals
    freshness_score: float        # Based on last update
    usage_count: int              # Times shown in results
    positive_count: int           # Positive feedbacks
    negative_count: int           # Negative feedbacks
    last_calculated: datetime
```

### Score Calculation

```python
class QualityScorer:
    WEIGHTS = {
        "feedback": 0.35,
        "behavior": 0.25,
        "relevance": 0.25,
        "freshness": 0.15
    }

    async def calculate_score(self, page_id: str) -> float:
        # Get all feedback for documents from this page
        feedbacks = await self.get_feedbacks_for_page(page_id)
        signals = await self.get_signals_for_page(page_id)
        usage = await self.get_usage_stats(page_id)
        page_info = await self.get_page_info(page_id)

        # Calculate component scores
        feedback_score = self.calc_feedback_score(feedbacks)
        behavior_score = self.calc_behavior_score(signals)
        relevance_score = self.calc_relevance_score(usage)
        freshness_score = self.calc_freshness_score(page_info.updated_at)

        # Weighted average
        quality = (
            self.WEIGHTS["feedback"] * feedback_score +
            self.WEIGHTS["behavior"] * behavior_score +
            self.WEIGHTS["relevance"] * relevance_score +
            self.WEIGHTS["freshness"] * freshness_score
        )

        return min(max(quality, 0.0), 1.0)  # Clamp to 0-1

    def calc_feedback_score(self, feedbacks: list[Feedback]) -> float:
        """Convert feedbacks to 0-1 score."""
        if not feedbacks:
            return 0.5  # Neutral default

        total_value = sum(f.feedback_value for f in feedbacks)
        # Normalize: -1 to +1 → 0 to 1
        avg = total_value / len(feedbacks)
        return (avg + 1) / 2

    def calc_behavior_score(self, signals: list[BehavioralSignal]) -> float:
        """Convert behavioral signals to 0-1 score."""
        if not signals:
            return 0.5

        total = sum(s.signal_value for s in signals)
        # Normalize similar to feedback
        avg = total / len(signals)
        return (avg + 1) / 2

    def calc_relevance_score(self, usage: UsageStats) -> float:
        """Score based on how often doc appears in useful answers."""
        if usage.times_shown == 0:
            return 0.5

        # Ratio of positive outcomes to total shows
        useful_ratio = usage.positive_outcomes / usage.times_shown
        return useful_ratio

    def calc_freshness_score(self, updated_at: datetime) -> float:
        """Score based on document age."""
        age_days = (datetime.utcnow() - updated_at).days

        if age_days < 30:
            return 1.0
        elif age_days < 90:
            return 0.9
        elif age_days < 180:
            return 0.7
        elif age_days < 365:
            return 0.5
        elif age_days < 730:
            return 0.3
        else:
            return 0.1
```

### ChromaDB Metadata Update

```python
async def update_chroma_quality_scores(self, scores: dict[str, float]):
    """Update quality_score in ChromaDB metadata."""
    for page_id, score in scores.items():
        # Get all chunks for this page
        chunk_ids = await self.get_chunk_ids_for_page(page_id)

        # Update metadata in ChromaDB
        # Note: ChromaDB requires re-upserting to update metadata
        for chunk_id in chunk_ids:
            existing = self.chroma.collection.get(ids=[chunk_id])
            metadata = existing["metadatas"][0]
            metadata["quality_score"] = score

            self.chroma.collection.update(
                ids=[chunk_id],
                metadatas=[metadata]
            )
```

### Celery Task

```python
@celery_app.task
def recalculate_quality_scores():
    """Daily task to recalculate all quality scores."""
    scorer = QualityScorer()

    # Get all pages
    page_ids = get_all_page_ids()

    scores = {}
    for page_id in page_ids:
        scores[page_id] = asyncio.run(scorer.calculate_score(page_id))

    # Update ChromaDB
    asyncio.run(update_chroma_quality_scores(scores))

    # Store in SQLite for reporting
    asyncio.run(store_quality_scores(scores))

    logger.info(f"Updated quality scores for {len(scores)} pages")
```

### CLI Command

```bash
# Recalculate all scores
python -m knowledge_base.cli scores recalculate

# Show score distribution
python -m knowledge_base.cli scores stats
```

## Definition of Done

- [ ] Quality scores calculated from feedback
- [ ] Behavioral signals included
- [ ] Freshness factored in
- [ ] ChromaDB metadata updated
- [ ] Scores used in search ranking
