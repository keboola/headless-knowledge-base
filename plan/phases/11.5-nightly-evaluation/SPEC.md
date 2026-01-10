# Phase 11.5: Nightly Evaluation

## Overview

Run automated LLM-as-Judge evaluation on sample of daily queries to detect quality degradation.

## Dependencies

- **Requires**: Phase 11 (Quality Scoring)
- **Blocks**: None (enhancement)
- **Enhances**: Quality monitoring

## Deliverables

```
src/knowledge_base/
├── evaluation/
│   ├── __init__.py
│   ├── llm_judge.py          # LLM evaluation
│   └── nightly_eval.py       # Nightly job
├── tasks/
│   └── evaluation_tasks.py   # Celery tasks
```

## Technical Specification

### Evaluation Metrics

| Metric | Description | Target |
|--------|-------------|--------|
| **Groundedness** | Is answer supported by retrieved docs? | >0.9 |
| **Relevance** | Are retrieved docs relevant to query? | >0.8 |
| **Completeness** | Does answer fully address query? | >0.7 |
| **No Hallucination** | No invented information? | >0.95 |

### LLM Judge

```python
class LLMJudge:
    def __init__(self, llm: BaseLLM):
        self.llm = llm

    async def evaluate_groundedness(
        self,
        answer: str,
        documents: list[str]
    ) -> float:
        """Check if answer is grounded in documents."""
        prompt = f"""Evaluate if this answer is fully supported by the provided documents.

Documents:
{self._format_docs(documents)}

Answer:
{answer}

Score from 0.0 (not grounded, contains made-up info) to 1.0 (fully grounded).
Only return the numeric score."""

        response = await self.llm.generate(prompt)
        return float(response.strip())

    async def evaluate_relevance(
        self,
        query: str,
        documents: list[str]
    ) -> float:
        """Check if retrieved documents are relevant."""
        prompt = f"""Evaluate if these documents are relevant to the question.

Question: {query}

Documents:
{self._format_docs(documents)}

Score from 0.0 (completely irrelevant) to 1.0 (highly relevant).
Only return the numeric score."""

        response = await self.llm.generate(prompt)
        return float(response.strip())

    async def evaluate_completeness(
        self,
        query: str,
        answer: str
    ) -> float:
        """Check if answer fully addresses the query."""
        prompt = f"""Evaluate if this answer fully addresses the question.

Question: {query}

Answer:
{answer}

Score from 0.0 (doesn't address at all) to 1.0 (fully addresses).
Only return the numeric score."""

        response = await self.llm.generate(prompt)
        return float(response.strip())
```

### Nightly Evaluator

```python
class NightlyEvaluator:
    def __init__(self, judge: LLMJudge, db: Database):
        self.judge = judge
        self.db = db

    async def run_nightly(self, sample_rate: float = 0.1):
        """Evaluate sample of today's queries."""
        # Get queries from last 24 hours
        queries = await self.db.get_queries_since(
            datetime.utcnow() - timedelta(days=1)
        )

        # Sample
        sample_size = int(len(queries) * sample_rate)
        sample = random.sample(queries, min(sample_size, len(queries)))

        results = []
        for query_record in sample:
            eval_result = await self.evaluate_query(query_record)
            results.append(eval_result)

        # Store results
        await self.store_results(results)

        # Generate report
        return self.generate_report(results)

    async def evaluate_query(self, record: QueryRecord) -> EvalResult:
        """Evaluate a single query-response pair."""
        groundedness = await self.judge.evaluate_groundedness(
            record.answer,
            record.retrieved_docs
        )
        relevance = await self.judge.evaluate_relevance(
            record.query,
            record.retrieved_docs
        )
        completeness = await self.judge.evaluate_completeness(
            record.query,
            record.answer
        )

        return EvalResult(
            query_id=record.id,
            groundedness=groundedness,
            relevance=relevance,
            completeness=completeness,
            overall=(groundedness + relevance + completeness) / 3
        )
```

### Evaluation Storage

```python
class EvalResult(Base):
    __tablename__ = "eval_results"

    id: int
    query_id: str
    groundedness: float
    relevance: float
    completeness: float
    overall: float
    evaluated_at: datetime
```

### Quality Report

```python
def generate_report(self, results: list[EvalResult]) -> QualityReport:
    """Generate daily quality report."""
    return QualityReport(
        date=datetime.utcnow().date(),
        sample_size=len(results),
        avg_groundedness=mean([r.groundedness for r in results]),
        avg_relevance=mean([r.relevance for r in results]),
        avg_completeness=mean([r.completeness for r in results]),
        avg_overall=mean([r.overall for r in results]),
        below_threshold=[
            r for r in results
            if r.groundedness < 0.7 or r.relevance < 0.6
        ]
    )
```

### Celery Task

```python
@celery_app.task
def run_nightly_evaluation():
    """Scheduled daily at 3 AM."""
    evaluator = NightlyEvaluator()
    report = asyncio.run(evaluator.run_nightly(sample_rate=0.1))

    # Log summary
    logger.info(f"Daily evaluation: {report.avg_overall:.2f} overall")

    # Alert if below threshold
    if report.avg_overall < 0.7:
        send_alert(f"RAG quality dropped to {report.avg_overall:.2f}")
```

### CLI Command

```bash
# Run evaluation manually
python -m knowledge_base.cli eval run --sample-rate=0.1

# View recent reports
python -m knowledge_base.cli eval reports --days=7
```

## Definition of Done

- [ ] LLM judge evaluates all metrics
- [ ] Nightly job runs on sample
- [ ] Results stored in database
- [ ] Quality report generated
- [ ] Alerts on quality drop
