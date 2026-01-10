# Phase 11.5: Nightly Evaluation - Checklist

## Pre-Implementation
- [ ] Read SPEC.md completely
- [ ] Verify Phase 11 is complete

## Implementation Tasks

### 1. Database Models
- [ ] Create `evaluation/__init__.py`
- [ ] Add EvalResult model
- [ ] Add QualityReport model
- [ ] Run migrations

### 2. Query Logging
- [ ] Log all queries with responses
- [ ] Store retrieved documents
- [ ] Store answers generated
- [ ] Track query IDs

### 3. LLM Judge
- [ ] Create `evaluation/llm_judge.py`
- [ ] Implement `evaluate_groundedness()`
- [ ] Implement `evaluate_relevance()`
- [ ] Implement `evaluate_completeness()`
- [ ] Handle LLM errors

### 4. Nightly Evaluator
- [ ] Create `evaluation/nightly_eval.py`
- [ ] Implement `run_nightly()`
- [ ] Implement sampling logic
- [ ] Store evaluation results

### 5. Report Generation
- [ ] Calculate aggregate metrics
- [ ] Identify below-threshold queries
- [ ] Generate summary report
- [ ] Track trends over time

### 6. Celery Integration
- [ ] Create `tasks/evaluation_tasks.py`
- [ ] Add to Celery Beat (3 AM daily)
- [ ] Add alerting on low scores

### 7. CLI Commands
- [ ] Add `eval run` command
- [ ] Add `eval reports` command
- [ ] Add `eval query <id>` command

## Post-Implementation
- [ ] Run tests from TEST.md
- [ ] Update PROGRESS.md status to ✅ Done
- [ ] Commit: "feat(phase-11.5): nightly evaluation"
