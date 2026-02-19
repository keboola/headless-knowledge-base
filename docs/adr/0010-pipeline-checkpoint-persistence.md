# ADR-0010: Pipeline Checkpoint Persistence via GCS FUSE

## Status
Accepted

## Date
2026-02-18

## Context
The Confluence-to-Graphiti indexing pipeline (`python -m knowledge_base.cli pipeline`) runs as a Cloud Run Job that processes 1000+ chunks. Each chunk requires multiple LLM calls via Graphiti (entity extraction, deduplication, edge resolution), making the full pipeline take 10-20+ hours at Vertex AI's rate limits.

Cloud Run Jobs have ephemeral filesystems -- when a job execution ends (success, timeout, or crash), all local data is lost. Without persistence, a crash at chunk 500 means restarting from chunk 1.

The pipeline uses SQLite (via SQLAlchemy async + aiosqlite) for local metadata (RawPage, Chunk tables) and checkpoint tracking (IndexingCheckpoint table). SQLite's WAL journal mode creates `-wal` and `-shm` shared memory files that require file-level locking, which is incompatible with network filesystems like GCS FUSE.

Additionally, SQLAlchemy's default connection pool (`QueuePool`) keeps idle connections alive that hold SQLite WAL file locks, causing "database is locked" errors when the checkpoint writer tries to acquire a write lock.

## Decision

We implemented crash-resilient checkpoint persistence using a combination of:

1. **GCS FUSE volume mount** on the Cloud Run Job container at `/mnt/pipeline-state`, backed by a GCS bucket with versioning enabled.

2. **Shell wrapper restore-on-start**: The job command copies the persisted DB from the FUSE mount to local disk before running the pipeline. This avoids pointing SQLite directly at the FUSE mount (WAL mode is incompatible with FUSE's lack of file locking).

3. **Raw aiosqlite for checkpoint writes**: The `GraphitiIndexer._flush_checkpoints()` method bypasses SQLAlchemy entirely, using `aiosqlite.connect()` directly to write checkpoint records. This eliminates contention with the SQLAlchemy connection pool.

4. **SQLAlchemy NullPool**: The async engine uses `poolclass=NullPool` so connections are closed immediately when sessions end, rather than being held in a pool that retains WAL file locks.

5. **WAL checkpoint before copy**: After each checkpoint flush, `PRAGMA wal_checkpoint(TRUNCATE)` merges WAL data into the main DB file. Without this, `shutil.copyfile` would only copy the main file, missing data still in the `-wal` file.

6. **Continuous persistence**: After every successful Graphiti batch (1-5 chunks), the checkpoint is flushed to SQLite and the entire DB is copied to the GCS FUSE mount via `shutil.copyfile`.

7. **ConfluenceDownloader with `index_to_graphiti=False`** in the pipeline command: The pipeline handles Graphiti indexing in a separate step (Step 3), after the download session is closed. Without this, the downloader would attempt Graphiti indexing while holding a SQLAlchemy session open, causing SQLite lock contention with the checkpoint writer.

### Pipeline Resume Flow

```
Start job
  |
  v
Shell wrapper: cp /mnt/pipeline-state/prod-knowledge-base.db ./knowledge_base.db
  |                 (fails silently on first run)
  v
Step 1: Download from Confluence (index_to_graphiti=False)
  -> Pages stored in SQLite as RawPage records
  |
Step 2: Parse pages into chunks
  -> Chunks stored in SQLite as Chunk records
  |
Step 3: Index into Graphiti
  -> Query IndexingCheckpoint for already-indexed chunk_ids
  -> Skip those chunks ("Resuming: N chunks already indexed")
  -> For each batch:
      1. Graphiti add_episode_bulk()
      2. Write checkpoint via raw aiosqlite
      3. PRAGMA wal_checkpoint(TRUNCATE)
      4. shutil.copyfile to /mnt/pipeline-state/
  |
  v
Complete (or crash/timeout -> next execution resumes)
```

## Rationale

### Why not point SQLite directly at GCS FUSE?
SQLite WAL mode requires POSIX file locking for the `-wal` and `-shm` files. GCS FUSE does not support file locking. Direct access causes corruption or "database is locked" errors.

### Why raw aiosqlite instead of SQLAlchemy for checkpoints?
SQLAlchemy's connection pool (even with NullPool) creates connections through the async engine's pool management layer. During the download and parse phases, SQLAlchemy sessions open connections that may not release file-level locks promptly. Using raw `aiosqlite.connect()` creates a completely independent connection that bypasses any pool contention.

### Why NullPool?
The default `QueuePool` keeps idle connections alive for reuse. With SQLite, these idle connections hold WAL file locks even after sessions close. `engine.dispose()` was tried but doesn't reliably close aiosqlite's threaded connections. NullPool closes connections immediately -- the correct behavior for SQLite where opening connections is nearly free.

### Why flush after every batch (not every 100 chunks)?
With Vertex AI's 5 RPM quota, processing 100 chunks takes ~5-7 hours. Flushing only at `INDEX_BATCH_SIZE=100` intervals means losing hours of progress on a crash. Flushing after every batch (1-5 chunks) adds negligible overhead (~10ms per flush) but provides crash resilience with at most a few minutes of lost work.

### Why GCS bucket versioning?
Protects against `shutil.copyfile` producing a corrupt/partial write during a crash. The previous version is recoverable from GCS object versioning.

## Consequences

### Positive
- Pipeline survives crashes, timeouts, and restarts without losing progress
- Kill-and-restart verified: execution resumed from 14 pre-indexed chunks
- GCS checkpoint file updated within 1 second of each indexed chunk
- No additional infrastructure (uses existing GCS FUSE support in Cloud Run Gen2)

### Negative
- Download and parse phases re-run on every restart (idempotent, ~10 minutes)
- Extra GCS write per chunk (~1140 writes per full pipeline run, negligible cost)
- `google-beta` Terraform provider required for GCS FUSE volume blocks
- `EXECUTION_ENVIRONMENT_GEN2` required on the Cloud Run Job

### Operational
- Checkpoint DB stored at `gs://ai-knowledge-base-42-pipeline-state/prod-knowledge-base.db`
- Staging variant at `staging-knowledge-base.db` in the same bucket
- To force a full reindex: use `--reindex` flag or delete the GCS checkpoint file
- Monitor: check GCS file timestamp to verify the pipeline is making progress

## References
- [Cloud Run GCS FUSE volumes](https://cloud.google.com/run/docs/configuring/services/cloud-storage-volume-mounts)
- [SQLite WAL mode](https://www.sqlite.org/wal.html)
- [SQLAlchemy NullPool](https://docs.sqlalchemy.org/en/20/core/pooling.html#using-a-pool-instance-directly)
- Terraform: `deploy/terraform/cloudrun-jobs.tf` (pipeline job + GCS bucket)
- Code: `src/knowledge_base/graph/graphiti_indexer.py` (`_flush_checkpoints`, `_persist_db`)
- Code: `src/knowledge_base/cli.py` (`_pipeline` function)
- Code: `src/knowledge_base/db/database.py` (NullPool engine)
