# Architecture Decision Records (ADR)

This directory contains Architecture Decision Records for the AI Knowledge Base project.

## What is an ADR?

An Architecture Decision Record captures an important architectural decision made along with its context and consequences.

## ADR Index

| ID | Title | Status | Date |
|----|-------|--------|------|
| [ADR-0001](0001-database-duckdb-on-gce.md) | Use DuckDB on GCE for Analytics Data | Accepted | 2024-12-24 (Updated 2026-01-03) |
| [ADR-0002](0002-vector-store-chromadb-on-cloudrun.md) | Use ChromaDB on Cloud Run Instead of Vertex AI Vector Search | Superseded | 2024-12-24 |
| [ADR-0003](0003-llm-provider-anthropic-claude.md) | Use Anthropic Claude API Instead of Vertex AI | Accepted | 2024-12-24 |
| [ADR-0004](0004-slack-bot-http-mode-cloudrun.md) | Deploy Slack Bot in HTTP Mode on Cloud Run | Accepted | 2024-12-24 |
| [ADR-0005](0005-chromadb-source-of-truth.md) | ChromaDB as Source of Truth for Knowledge Data | Superseded | 2026-01-03 |
| [ADR-0009](0009-neo4j-graphiti-knowledge-store.md) | Neo4j + Graphiti as Knowledge Store | Accepted | 2026-02-13 |

## Key Architecture Document

See [docs/ARCHITECTURE.md](../ARCHITECTURE.md) for the master architecture principles that govern all ADRs.

## ADR Template

When creating a new ADR, use this template:

```markdown
# ADR-XXXX: Title

## Status
[Proposed | Accepted | Deprecated | Superseded]

## Date
YYYY-MM-DD

## Context
What is the issue that we're seeing that is motivating this decision?

## Decision
What is the change that we're proposing and/or doing?

## Rationale
Why did we choose this option over alternatives?

## Consequences
What becomes easier or harder because of this decision?

## References
Links to relevant documentation, pricing pages, etc.
```

## Decision Criteria

Our architectural decisions prioritize:
1. **Cost-effectiveness** - Small/cost-sensitive deployment
2. **Simplicity** - Minimize operational complexity
3. **Portability** - Avoid vendor lock-in where practical
4. **Scalability path** - Document migration options for growth
