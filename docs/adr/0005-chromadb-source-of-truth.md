# ADR-0005: ChromaDB as Source of Truth for Knowledge Data

## Status
Accepted

## Date
2026-01-03

## Context

The original implementation stored knowledge data in multiple places:

1. **SQLite (SQLAlchemy models)**: RawPage, Chunk, ChunkMetadata, ChunkQuality, GovernanceMetadata, and 12+ other models
2. **ChromaDB**: Embeddings + documents + metadata (synced from SQLite)

This dual-storage approach created several problems:

### Problems with Current Architecture

1. **Data duplication**: Same information stored in two databases
2. **Sync complexity**: Quality scores and governance metadata had to be synchronized between SQLite and ChromaDB via `metadata_sync.py`
3. **Inconsistency risk**: If sync fails, databases become out of sync
4. **Unnecessary complexity**: 17 SQLAlchemy models when most data belongs in ChromaDB
5. **Confused source of truth**: Developers unsure which database to query/update

### Requirements

- Simple, clear data architecture
- Single source of truth for each piece of data
- Fast search operations (quality filtering, governance filtering)
- Preserve user feedback for future model retraining
- Support analytics on user behavior

## Decision

**ChromaDB is the source of truth for all knowledge data.**

DuckDB stores **only** user feedback and behavioral signals for analytics and potential retraining.

### What Goes Where

| Data Type | Database | Rationale |
|-----------|----------|-----------|
| Chunk content | ChromaDB | Primary search store |
| Embeddings | ChromaDB | Vector search |
| Quality scores | ChromaDB metadata | Filter during search, no sync needed |
| Governance (owner, classification) | ChromaDB metadata | Filter during search |
| Page metadata (title, url, author) | ChromaDB metadata | Denormalized for search |
| AI metadata (topics, doc_type) | ChromaDB metadata | Filter during search |
| User feedback | DuckDB | Retraining data, not needed in search |
| Behavioral signals | DuckDB | Analytics only |

### Quality Score Management

Quality scores are managed **natively in ChromaDB**:

```python
# On feedback submission
chroma_client.update(
    ids=[chunk_id],
    metadatas=[{"quality_score": new_score}]
)

# Optionally log to DuckDB for analytics
duckdb.execute("INSERT INTO user_feedback ...")
```

No sync layer needed. ChromaDB is the authoritative source.

## Rationale

### Why ChromaDB for Everything?

1. **Search performance**: All search filters (quality, governance, topics) can be applied in a single ChromaDB query
2. **No sync complexity**: Updates happen in one place
3. **Atomic operations**: Chunk + metadata updated together
4. **ChromaDB supports rich metadata**: Arbitrary key-value pairs, no schema constraints

### Why Keep DuckDB for Feedback?

1. **Retraining data**: User corrections valuable for future model improvement
2. **Analytics**: SQL queries for usage patterns
3. **Separation of concerns**: Feedback is about user behavior, not knowledge content
4. **Different lifecycle**: Feedback accumulates over time, knowledge is refreshed from source

### Why Not SQLite for Feedback?

1. **DuckDB excels at analytics**: Better for aggregations and reporting
2. **Cost alignment**: DuckDB on GCE is our chosen persistence layer (ADR-0001)
3. **Consistency**: Single relational database for all analytics needs

## Consequences

### Positive

1. **Simpler architecture**: Two databases with clear responsibilities
2. **No sync bugs**: Eliminate entire class of inconsistency issues
3. **Faster feedback**: Update quality in one place, immediately searchable
4. **Easier reasoning**: Developers know exactly where each data type lives
5. **Reduced codebase**: Remove 15+ unused SQLAlchemy models

### Negative

1. **Migration effort**: Existing code needs refactoring
2. **No relational queries on knowledge**: Can't JOIN chunks with other tables
3. **ChromaDB dependency**: More critical to system operation

### Migration Path

1. **Phase 1** (This ADR): Document the target architecture
2. **Phase 2**: Update ingestion to write all metadata to ChromaDB
3. **Phase 3**: Update feedback handlers to write quality directly to ChromaDB
4. **Phase 4**: Migrate feedback tables from SQLite to DuckDB
5. **Phase 5**: Remove unused SQLAlchemy models

## References

- [docs/ARCHITECTURE.md](../ARCHITECTURE.md) - Master architecture principles
- [ADR-0001](0001-database-duckdb-on-gce.md) - DuckDB for analytics
- [ADR-0002](0002-vector-store-chromadb-on-cloudrun.md) - ChromaDB deployment
- [ChromaDB Metadata Filtering](https://docs.trychroma.com/usage-guide#filtering-by-metadata)
