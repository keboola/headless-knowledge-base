# ADR-0006: Use Ephemeral Local DuckDB in Cloud Run

## Status
Accepted

## Date
2026-01-09

## Context

The Slack bot running on Cloud Run was failing to respond to @mentions because DuckDB initialization was blocking the Q&A flow. The original implementation (per [ADR-0001](0001-database-duckdb-on-gce.md)) attempted to connect to a remote DuckDB server using:

```python
connection_string = f"md:{settings.DUCKDB_HOST}:{settings.DUCKDB_PORT}"
```

This caused two issues:
1. The `md:` prefix triggered MotherDuck (cloud DuckDB) authentication flow
2. No MotherDuck token was configured, causing immediate failure
3. The failure crashed the entire Q&A handler before reaching ChromaDB

### The Real Question

DuckDB stores only analytics data (feedback, behavioral signals). The question became:

> Do we need persistent analytics data across container restarts, or is ephemeral storage acceptable?

## Decision

Use **ephemeral local DuckDB** (file-based in `/tmp`) for Cloud Run deployments instead of remote DuckDB server.

```python
if settings.DUCKDB_HOST:
    # GCP deployment: local file-based DuckDB
    db_path = Path("/tmp/analytics.duckdb")
    _duckdb_conn = duckdb.connect(str(db_path))
```

## Rationale

### Why Ephemeral is Acceptable

1. **Analytics data is supplementary**: The core knowledge (ChromaDB) is unaffected
2. **Feedback is already in Slack**: Users can re-submit feedback if needed
3. **Behavioral signals are best-effort**: Missing some signals doesn't break functionality
4. **Low volume**: Analytics queries are infrequent (admin reports)

### Why Not Remote DuckDB

1. **Complexity**: Requires running a separate DuckDB server on GCE
2. **Cost**: Additional VM cost (~$5-10/month) for low-value data
3. **Network latency**: Every Q&A request would wait for DuckDB connection
4. **Single point of failure**: If DuckDB server is down, all Q&A fails

### Why Not MotherDuck

1. **Authentication complexity**: Requires token management
2. **Network dependency**: Cloud service adds latency and failure modes
3. **Overkill**: We don't need cloud-scale analytics for internal bot

## Consequences

### Positive
- Simpler architecture: No external DuckDB dependency for Slack bot
- Faster startup: No remote connection needed
- More resilient: Q&A works even if analytics fails
- Lower cost: Eliminates need for dedicated DuckDB GCE instance

### Negative
- Analytics data is lost on container restart
- Cannot aggregate feedback across multiple container instances
- No historical analytics reports without additional implementation

### Future Options

If persistent analytics becomes important:
1. **BigQuery streaming**: Send events to BigQuery for durable analytics
2. **Cloud SQL**: Use managed PostgreSQL for feedback storage
3. **Firestore**: Use serverless document DB for event storage

## Related

- [ADR-0001](0001-database-duckdb-on-gce.md) - Original DuckDB decision (partially superseded)
- [ADR-0005](0005-chromadb-source-of-truth.md) - ChromaDB as source of truth for knowledge
