# Phase 11.5: Nightly Evaluation - Test Plan

## Quick Verification

```bash
# Run evaluation manually
python -m knowledge_base.cli eval run --sample-rate=0.5

# View results
python -m knowledge_base.cli eval reports
```

## Functional Tests

### 1. Single Query Evaluation
```bash
# Evaluate specific query
python -c "
from knowledge_base.evaluation.llm_judge import LLMJudge
import asyncio

async def test():
    judge = LLMJudge()

    answer = 'You can request PTO through Workday.'
    docs = ['PTO is requested via the Workday portal.']

    groundedness = await judge.evaluate_groundedness(answer, docs)
    print(f'Groundedness: {groundedness}')

asyncio.run(test())
"
# Expected: Score close to 1.0 (answer matches docs)
```

### 2. Hallucination Detection
```bash
python -c "
from knowledge_base.evaluation.llm_judge import LLMJudge
import asyncio

async def test():
    judge = LLMJudge()

    # Answer contains info not in docs
    answer = 'PTO requires manager approval within 24 hours.'
    docs = ['PTO is requested via Workday.']

    groundedness = await judge.evaluate_groundedness(answer, docs)
    print(f'Groundedness: {groundedness}')

asyncio.run(test())
"
# Expected: Score < 0.5 (hallucination detected)
```

### 3. Nightly Run
```bash
# Generate some queries first (via Slack or API)
# Then run evaluation

python -m knowledge_base.cli eval run --sample-rate=1.0

# Check results
sqlite3 knowledge_base.db "
SELECT
    query_id,
    groundedness,
    relevance,
    completeness,
    overall
FROM eval_results
ORDER BY evaluated_at DESC
LIMIT 10;
"
```

### 4. Report Generation
```bash
python -m knowledge_base.cli eval reports --days=1

# Should show:
# - Sample size
# - Average scores
# - Any below-threshold queries
```

### 5. Trend Analysis
```bash
# After running for several days
sqlite3 knowledge_base.db "
SELECT
    date(evaluated_at) as date,
    AVG(overall) as avg_overall,
    COUNT(*) as sample_size
FROM eval_results
GROUP BY date(evaluated_at)
ORDER BY date DESC;
"
```

## Unit Tests

```python
# tests/test_evaluation.py
import pytest
from knowledge_base.evaluation.llm_judge import LLMJudge
from knowledge_base.evaluation.nightly_eval import NightlyEvaluator

@pytest.mark.asyncio
async def test_groundedness_high():
    judge = LLMJudge()

    answer = "The office opens at 9 AM."
    docs = ["Office hours are 9 AM to 5 PM."]

    score = await judge.evaluate_groundedness(answer, docs)
    assert score > 0.7

@pytest.mark.asyncio
async def test_groundedness_low():
    judge = LLMJudge()

    answer = "The office has a gym and pool."
    docs = ["Office hours are 9 AM to 5 PM."]

    score = await judge.evaluate_groundedness(answer, docs)
    assert score < 0.5

@pytest.mark.asyncio
async def test_relevance_high():
    judge = LLMJudge()

    query = "What are the office hours?"
    docs = ["Office hours are 9 AM to 5 PM Monday through Friday."]

    score = await judge.evaluate_relevance(query, docs)
    assert score > 0.8

@pytest.mark.asyncio
async def test_relevance_low():
    judge = LLMJudge()

    query = "What are the office hours?"
    docs = ["The company was founded in 2010."]

    score = await judge.evaluate_relevance(query, docs)
    assert score < 0.3

def test_report_generation():
    evaluator = NightlyEvaluator()

    results = [
        MockEvalResult(0.9, 0.8, 0.7),
        MockEvalResult(0.8, 0.9, 0.8),
        MockEvalResult(0.5, 0.6, 0.5),  # Below threshold
    ]

    report = evaluator.generate_report(results)

    assert report.sample_size == 3
    assert len(report.below_threshold) == 1
    assert report.avg_groundedness == pytest.approx(0.73, 0.1)
```

## Integration Test

```python
@pytest.mark.asyncio
async def test_full_evaluation_pipeline():
    # Create some query records
    query_ids = []
    for i in range(5):
        query_id = await store_query_record(
            query=f"Test query {i}",
            answer=f"Test answer {i}",
            docs=[f"Test doc {i}"]
        )
        query_ids.append(query_id)

    # Run evaluation
    evaluator = NightlyEvaluator()
    report = await evaluator.run_nightly(sample_rate=1.0)

    # Verify results stored
    results = await get_eval_results(query_ids)
    assert len(results) == 5

    # Verify report generated
    assert report.sample_size == 5
```

## Success Criteria

- [ ] LLM judge returns valid scores
- [ ] Hallucinations detected (low groundedness)
- [ ] Irrelevant docs detected (low relevance)
- [ ] Nightly job completes successfully
- [ ] Reports show trends
- [ ] Alerts trigger on low scores
