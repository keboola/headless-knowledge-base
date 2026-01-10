# Phase 11: Quality Scoring - Checklist

## Pre-Implementation
- [ ] Read SPEC.md completely
- [ ] Verify Phase 10 and 10.5 are complete

## Implementation Tasks

### 1. Database Model
- [ ] Add DocumentQuality model
- [ ] Add UsageStats tracking
- [ ] Run migrations

### 2. Score Calculator
- [ ] Create `feedback/scorer.py`
- [ ] Implement `calc_feedback_score()`
- [ ] Implement `calc_behavior_score()`
- [ ] Implement `calc_relevance_score()`
- [ ] Implement `calc_freshness_score()`
- [ ] Implement `calculate_score()`

### 3. Usage Tracking
- [ ] Track when documents shown
- [ ] Track positive/negative outcomes
- [ ] Link usage to feedback

### 4. ChromaDB Updates
- [ ] Implement metadata update
- [ ] Handle bulk updates efficiently
- [ ] Verify scores stored correctly

### 5. Celery Task
- [ ] Create `tasks/scoring_tasks.py`
- [ ] Implement `recalculate_quality_scores`
- [ ] Add to Celery Beat schedule
- [ ] Handle errors gracefully

### 6. Search Integration
- [ ] Use quality_score in ranking
- [ ] Boost high-quality documents
- [ ] Test ranking changes

### 7. CLI Commands
- [ ] Add `scores recalculate` command
- [ ] Add `scores stats` command
- [ ] Add `scores show <page_id>` command

## Post-Implementation
- [ ] Run tests from TEST.md
- [ ] Update PROGRESS.md status to ✅ Done
- [ ] Commit: "feat(phase-11): quality scoring"
