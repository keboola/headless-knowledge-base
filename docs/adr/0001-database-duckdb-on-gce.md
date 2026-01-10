# ADR-0001: Use DuckDB on GCE for Analytics Data

## Status
Partially Superseded (Updated 2026-01-09)

> **UPDATE 2026-01-09**: For the Slack bot on Cloud Run, DuckDB now uses ephemeral local storage instead of remote GCE server. See [ADR-0006](0006-duckdb-ephemeral-local-storage.md). The GCE DuckDB instance may still be used for batch jobs.

## Date
2024-12-24 (Updated 2026-01-03)

## Context

> **UPDATE 2026-01-03**: This ADR has been updated to reflect the narrowed scope of DuckDB. Per [ADR-0005](0005-chromadb-source-of-truth.md), ChromaDB is now the source of truth for all knowledge data. DuckDB stores only analytics and feedback data.

The application requires a relational database for storing **user feedback and behavioral signals** for analytics and potential model retraining.

For GCP deployment, we chose between:
1. **Cloud SQL (PostgreSQL/MySQL)** - Managed relational database
2. **AlloyDB** - High-performance PostgreSQL
3. **DuckDB on GCE** - Analytical database on a dedicated instance

### Requirements
- Small/cost-sensitive deployment
- Analytics queries on user behavior
- Storage for feedback data (retraining corpus)
- Low write volume (only feedback events)

### What DuckDB Stores (Narrowed Scope)

| Table | Purpose |
|-------|---------|
| `user_feedback` | Explicit feedback (helpful, incorrect, outdated, confusing) with comments |
| `behavioral_signal` | Implicit signals (thanks, frustration, reactions) for analytics |

### What DuckDB Does NOT Store

Per [ADR-0005](0005-chromadb-source-of-truth.md), the following are stored in **ChromaDB**:
- Document chunks and content
- Quality scores
- Page metadata
- Governance information
- AI-generated metadata (topics, doc_type, etc.)

## Decision
We chose **DuckDB running on a GCE e2-micro instance with Persistent Disk** for analytics data only.

## Rationale

### Cost Comparison
| Option | Monthly Cost |
|--------|-------------|
| DuckDB on GCE (e2-micro + 20GB SSD) | ~$5-10 |
| Cloud SQL (db-f1-micro) | ~$30-50 |
| AlloyDB | ~$100+ |

### Why DuckDB?
1. **Cost-effective**: 5-10x cheaper than Cloud SQL for our scale
2. **Analytical performance**: Excellent for aggregations and reporting on feedback data
3. **Simple operations**: Single file database, easy backups
4. **SQL support**: Standard SQL for analytics queries

### Why GCE instead of Cloud Run?
1. **Stateful storage**: Persistent Disk provides durable storage
2. **Always-on**: No cold start latency for database queries
3. **Private networking**: No public IP, accessible only via VPC

### Trade-offs Accepted
- **Single writer**: Only one instance can write at a time
- **No automatic failover**: Manual intervention needed if instance fails
- **Limited scalability**: Vertical scaling only (larger instance)

## Consequences

### Positive
- Significantly lower operational costs (~$5-10/month vs $30-50/month)
- Simpler architecture for small-scale deployment
- Fast analytical queries for feedback reporting
- Clean separation: ChromaDB for knowledge, DuckDB for analytics

### Negative
- Cannot scale horizontally for write-heavy workloads
- No built-in high availability
- Requires custom HTTP API wrapper for remote access

### Migration Path
If scaling is needed in the future:
1. Export data from DuckDB
2. Import into Cloud SQL PostgreSQL
3. Update connection strings in configuration

## References
- [ADR-0005](0005-chromadb-source-of-truth.md) - ChromaDB as source of truth
- [docs/ARCHITECTURE.md](../ARCHITECTURE.md) - Master architecture principles
- [DuckDB Documentation](https://duckdb.org/docs/)
- [GCP Compute Engine Pricing](https://cloud.google.com/compute/pricing)
- [Cloud SQL Pricing](https://cloud.google.com/sql/pricing)
