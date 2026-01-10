# Phase 12: Governance Reports

## Overview

Identify obsolete content, documentation gaps, and generate governance reports for content maintainers.

## Dependencies

- **Requires**: Phase 11 (Quality Scoring)
- **Blocks**: None

## Deliverables

```
src/knowledge_base/
├── governance/
│   ├── __init__.py
│   ├── obsolete_detector.py  # Find stale content
│   ├── gap_analyzer.py       # Find unanswered queries
│   └── reports.py            # Generate reports
├── api/
│   └── governance.py         # Governance endpoints
```

## Technical Specification

### Obsolete Content Detection

```python
class ObsoleteDetector:
    def __init__(
        self,
        max_age_days: int = 730,        # 2 years
        min_quality: float = 0.3
    ):
        self.max_age_days = max_age_days
        self.min_quality = min_quality

    async def find_obsolete(self) -> list[ObsoleteDocument]:
        """Find documents that should be reviewed/removed."""
        obsolete = []

        for page in await self.get_all_pages():
            reasons = []

            # Check age
            age_days = (datetime.utcnow() - page.updated_at).days
            if age_days > self.max_age_days:
                reasons.append(f"Not updated in {age_days} days")

            # Check quality score
            quality = await self.get_quality_score(page.id)
            if quality < self.min_quality:
                reasons.append(f"Low quality score: {quality:.2f}")

            # Check negative feedback ratio
            feedback = await self.get_feedback_stats(page.id)
            if feedback.negative_ratio > 0.5:
                reasons.append(f"High negative feedback: {feedback.negative_ratio:.0%}")

            # Check usage
            usage = await self.get_usage_stats(page.id)
            if usage.times_shown > 10 and usage.click_through_rate < 0.1:
                reasons.append(f"Low engagement: {usage.click_through_rate:.0%} CTR")

            if reasons:
                obsolete.append(ObsoleteDocument(
                    page_id=page.id,
                    title=page.title,
                    space_key=page.space_key,
                    last_updated=page.updated_at,
                    quality_score=quality,
                    reasons=reasons
                ))

        return obsolete
```

### Gap Analyzer

```python
class GapAnalyzer:
    def __init__(self, embedding_model, min_cluster_size: int = 3):
        self.embeddings = embedding_model
        self.min_cluster_size = min_cluster_size

    async def find_gaps(self) -> list[DocumentationGap]:
        """Find topics with queries but poor/no documentation."""
        # Get failed/low-quality queries
        failed_queries = await self.get_failed_queries()

        # Cluster similar queries
        clusters = await self.cluster_queries(failed_queries)

        gaps = []
        for cluster in clusters:
            if len(cluster.queries) >= self.min_cluster_size:
                gaps.append(DocumentationGap(
                    topic=cluster.representative_query,
                    query_count=len(cluster.queries),
                    sample_queries=cluster.queries[:5],
                    suggested_title=await self.generate_title(cluster)
                ))

        return sorted(gaps, key=lambda g: g.query_count, reverse=True)

    async def cluster_queries(self, queries: list[str]) -> list[QueryCluster]:
        """Group similar queries using embeddings."""
        # Get embeddings
        embeddings = await self.embeddings.embed(queries)

        # Cluster (simple: cosine similarity threshold)
        clusters = []
        used = set()

        for i, q1 in enumerate(queries):
            if i in used:
                continue

            cluster = [q1]
            used.add(i)

            for j, q2 in enumerate(queries):
                if j in used:
                    continue

                similarity = cosine_similarity(embeddings[i], embeddings[j])
                if similarity > 0.8:
                    cluster.append(q2)
                    used.add(j)

            clusters.append(QueryCluster(
                queries=cluster,
                representative_query=cluster[0]
            ))

        return clusters
```

### Coverage Matrix

```python
class CoverageAnalyzer:
    async def get_topic_coverage(self) -> CoverageMatrix:
        """Map topics to document count and quality."""
        topics = await self.get_all_topics()
        coverage = {}

        for topic in topics:
            docs = await self.get_docs_for_topic(topic)
            coverage[topic] = TopicCoverage(
                doc_count=len(docs),
                avg_quality=mean([d.quality_score for d in docs]) if docs else 0,
                query_count=await self.get_query_count_for_topic(topic),
                coverage_ratio=len(docs) / max(1, await self.get_query_count_for_topic(topic))
            )

        return CoverageMatrix(coverage)
```

### API Endpoints

```python
@router.get("/api/v1/governance/obsolete")
async def get_obsolete_docs():
    """List documents flagged as obsolete."""
    detector = ObsoleteDetector()
    return await detector.find_obsolete()

@router.get("/api/v1/governance/gaps")
async def get_gaps():
    """List documentation gaps (unanswered topics)."""
    analyzer = GapAnalyzer()
    return await analyzer.find_gaps()

@router.get("/api/v1/governance/coverage")
async def get_coverage():
    """Get topic coverage matrix."""
    analyzer = CoverageAnalyzer()
    return await analyzer.get_topic_coverage()

@router.get("/api/v1/governance/low-quality")
async def get_low_quality():
    """List low-quality documents."""
    return await get_docs_below_quality_threshold(0.4)
```

### Governance Issue Tracking

```python
class GovernanceIssue(Base):
    __tablename__ = "governance_issues"

    id: int
    page_id: str | None           # For doc issues
    issue_type: str               # "obsolete", "low_quality", "gap"
    description: str
    severity: str                 # "low", "medium", "high"
    detected_at: datetime
    resolved_at: datetime | None
    assigned_to: str | None
```

## CLI Commands

```bash
# Generate full report
python -m knowledge_base.cli governance report

# List obsolete docs
python -m knowledge_base.cli governance obsolete

# List gaps
python -m knowledge_base.cli governance gaps

# Export to CSV
python -m knowledge_base.cli governance export --format=csv
```

## Definition of Done

- [ ] Obsolete docs detected and listed
- [ ] Documentation gaps identified
- [ ] Topic coverage matrix generated
- [ ] API endpoints working
- [ ] Issues tracked in database
