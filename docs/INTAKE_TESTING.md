# Confluence Intake Pipeline Testing Guide

This guide explains how to test the new Confluence intake pipeline with checkpoint/resume and parallel processing capabilities.

## Quick Start

### Clear Neo4j and Run Intake Test

```bash
# 1. Make scripts executable
chmod +x deploy/scripts/clear-neo4j-staging.sh
chmod +x deploy/scripts/test-intake-pipeline.sh

# 2. Run with conservative concurrency (recommended first test)
./deploy/scripts/test-intake-pipeline.sh --concurrency 3 --space KI

# 3. Monitor logs
gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="confluence-sync"' --limit=100
```

## Full Testing Workflow

### Phase 1: Setup

```bash
# Clear Neo4j staging data
./deploy/scripts/clear-neo4j-staging.sh

# Verify Neo4j is empty
gcloud compute ssh neo4j-staging --zone=us-central1-a \
  --command='docker exec neo4j-staging cypher-shell -u neo4j "MATCH (n) RETURN COUNT(n)"'
# Should return: 0
```

### Phase 2: Run Initial Intake

```bash
# Test with conservative concurrency (3 concurrent chunks)
./deploy/scripts/test-intake-pipeline.sh \
  --concurrency 3 \
  --space KI

# Note the start/end times and duration
```

### Phase 3: Monitor Progress

```bash
# Option 1: Real-time logs (while job is running)
gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="confluence-sync"' \
  --limit=50 --follow

# Option 2: Check checkpoint table (SSH to staging environment)
sqlite3 data/knowledge_base.db \
  "SELECT status, COUNT(*) as count FROM indexing_checkpoints GROUP BY status"

# Expected output after partial run:
# indexed|500
# failed|10
# pending|490

# Option 3: Verify Neo4j has data
gcloud compute ssh neo4j-staging --zone=us-central1-a \
  --command='docker exec neo4j-staging cypher-shell -u neo4j "MATCH (n) RETURN COUNT(n)"'
```

### Phase 4: Test Resume Capability

If the job was interrupted:

```bash
# Resume from checkpoint (skip already-indexed chunks)
./deploy/scripts/test-intake-pipeline.sh \
  --concurrency 3 \
  --space KI \
  --resume

# Should log: "Resuming: 500 chunks already indexed, skipping them"
# Should only process remaining ~490 chunks
```

### Phase 5: Performance Validation

```bash
# Scale up concurrency if Phase 2 was successful
./deploy/scripts/test-intake-pipeline.sh \
  --concurrency 5 \
  --space KI

# Compare times:
# - With CONCURRENCY=3: ~X minutes
# - With CONCURRENCY=5: ~Y minutes
# Expected: 5x speedup over sequential (CONCURRENCY=1)
```

## Manual Testing Commands

### View Pipeline Status

```bash
# Show job execution details
gcloud run jobs describe confluence-sync --region=us-central1

# Show recent executions
gcloud run jobs list --region=us-central1

# View full logs (last 500 lines)
gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="confluence-sync"' \
  --limit=500 \
  --format='table(timestamp, textPayload)'
```

### Database Queries

```bash
# Check checkpoint statistics
sqlite3 data/knowledge_base.db << EOF
SELECT
  status,
  COUNT(*) as count,
  ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM indexing_checkpoints), 2) as percentage
FROM indexing_checkpoints
GROUP BY status;
EOF

# Check error messages
sqlite3 data/knowledge_base.db << EOF
SELECT
  error_message,
  COUNT(*) as count
FROM indexing_checkpoints
WHERE status = 'failed'
GROUP BY error_message
LIMIT 10;
EOF

# Check session performance
sqlite3 data/knowledge_base.db << EOF
SELECT
  session_id,
  COUNT(*) as total_chunks,
  SUM(CASE WHEN status = 'indexed' THEN 1 ELSE 0 END) as indexed,
  SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
FROM indexing_checkpoints
GROUP BY session_id
ORDER BY session_id DESC;
EOF

# Clear checkpoint data (to start fresh test)
sqlite3 data/knowledge_base.db "DELETE FROM indexing_checkpoints;"
```

### Neo4j Verification

```bash
# SSH to staging instance
gcloud compute ssh neo4j-staging --zone=us-central1-a

# Inside instance:

# Count all nodes
docker exec neo4j-staging cypher-shell -u neo4j -p <password> "MATCH (n) RETURN COUNT(n)"

# Count by type
docker exec neo4j-staging cypher-shell -u neo4j -p <password> "MATCH (n) RETURN labels(n), COUNT(*)"

# Check recent episodes (chunks)
docker exec neo4j-staging cypher-shell -u neo4j -p <password> \
  "MATCH (e:Episode) RETURN e.chunk_id, e.content LIMIT 10"

# Verify relationships
docker exec neo4j-staging cypher-shell -u neo4j -p <password> \
  "MATCH (e:Episode)-[r]->(n) RETURN TYPE(r), COUNT(*) GROUP BY TYPE(r)"
```

## Unit Tests

### Run All Intake Tests

```bash
# Run only intake pipeline tests
pytest tests/integration/test_intake_pipeline.py -v

# Run specific test class
pytest tests/integration/test_intake_pipeline.py::TestCheckpointSystem -v

# Run specific test
pytest tests/integration/test_intake_pipeline.py::TestCheckpointSystem::test_checkpoint_write_and_flush -v

# Run with coverage
pytest tests/integration/test_intake_pipeline.py --cov=src.knowledge_base.graph.graphiti_indexer
```

### Test Categories

1. **Checkpoint System Tests**
   - `test_checkpoint_write_and_flush` - Verify checkpoints are buffered and flushed
   - `test_checkpoint_upsert_on_retry` - Verify retry count increments on upsert
   - `test_resume_query_excludes_indexed` - Verify resume query works correctly

2. **Circuit Breaker Tests**
   - `test_circuit_breaker_states` - Verify state machine (CLOSED/OPEN/HALF_OPEN)
   - `test_circuit_breaker_recovery` - Verify recovery after cooldown
   - `test_circuit_breaker_blocks_on_rate_limits` - Verify blocking on failures

3. **Parallel Indexing Tests**
   - `test_parallel_mode_with_semaphore` - Verify concurrency limiting
   - `test_sequential_vs_parallel_produces_same_results` - Verify same output

4. **Resume Tests**
   - `test_resume_skips_indexed_chunks` - Verify indexed chunks are skipped

## Expected Results

### Baseline Performance (Before Optimization)
```
Concurrency: 1 (sequential)
Time for 1000 chunks: 60-120 minutes
Throughput: 0.13-0.28 chunks/second
```

### After Optimization
```
Concurrency: 3 (conservative)
Time for 1000 chunks: 20-40 minutes
Throughput: 0.42-0.84 chunks/second
Improvement: ~3x faster

Concurrency: 5 (default)
Time for 1000 chunks: 12-24 minutes
Throughput: 0.7-1.4 chunks/second
Improvement: ~5x faster

Concurrency: 10 (aggressive)
Time for 1000 chunks: 6-12 minutes
Throughput: 1.4-2.8 chunks/second
Improvement: ~10x faster
```

### Success Metrics
- Success rate: 90%+ (same or better than before)
- Rate limit errors: <10% of chunks
- Circuit breaker opens: <1 per 100 runs (should be rare)
- Resume works: Restarted jobs skip indexed chunks (0% wasted work)

## Troubleshooting

### Jobs Timeout

**Symptom**: Job execution times out before completing

**Troubleshooting**:
1. Check rate limit frequency in logs: `grep "rate limit" logs`
2. Reduce concurrency: `--concurrency 3` instead of 5
3. Check Neo4j performance: `docker exec neo4j-staging cypher-shell "MATCH (n) RETURN COUNT(n)"`
4. Increase Cloud Run job timeout in terraform

### Resume Flag Not Working

**Symptom**: Resume flag doesn't skip chunks

**Troubleshooting**:
1. Verify checkpoint table has data: `sqlite3 data/knowledge_base.db "SELECT COUNT(*) FROM indexing_checkpoints"`
2. Check status values: `SELECT DISTINCT status FROM indexing_checkpoints`
3. Ensure chunks were actually indexed (check status='indexed')

### Circuit Breaker Opening Too Frequently

**Symptom**: Logs show "Circuit breaker OPEN" frequently

**Troubleshooting**:
1. Reduce concurrency (fewer concurrent requests)
2. Increase rate limit threshold: `GRAPHITI_RATE_LIMIT_THRESHOLD=10`
3. Increase cooldown: `GRAPHITI_CIRCUIT_BREAKER_COOLDOWN=120`
4. Check LLM API status and quota

### High Error Rate

**Symptom**: Many chunks fail (status='failed')

**Troubleshooting**:
1. Check error messages: `sqlite3 data/knowledge_base.db "SELECT error_message, COUNT(*) FROM indexing_checkpoints WHERE status='failed' GROUP BY error_message"`
2. Verify LLM API credentials
3. Check Neo4j available space
4. Verify Confluence connectivity

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Test Intake Pipeline

on:
  push:
    paths:
      - 'src/knowledge_base/graph/graphiti_indexer.py'
      - 'src/knowledge_base/cli.py'
      - 'src/knowledge_base/db/models.py'
  workflow_dispatch:
    inputs:
      concurrency:
        description: 'Concurrency level'
        required: false
        default: '3'

jobs:
  test-intake:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install -e .

      - name: Run unit tests
        run: pytest tests/integration/test_intake_pipeline.py -v

      - name: Run staging test (if credentials available)
        if: ${{ secrets.GCP_SA_KEY != '' }}
        env:
          GOOGLE_APPLICATION_CREDENTIALS: /tmp/gcp-key.json
          PROJECT_ID: ai-knowledge-base-42
        run: |
          echo "${{ secrets.GCP_SA_KEY }}" > /tmp/gcp-key.json
          gcloud auth activate-service-account --key-file=/tmp/gcp-key.json
          ./deploy/scripts/test-intake-pipeline.sh \
            --concurrency ${{ inputs.concurrency || 3 }} \
            --space KI
```

## Monitoring & Alerts

### Metrics to Track

1. **Indexing Time**: Should decrease with parallelism
2. **Success Rate**: Should stay 90%+
3. **Rate Limit Errors**: Should be <10%
4. **Circuit Breaker Events**: Should be rare
5. **Checkpoint Table Size**: Should grow linearly (not exponentially)

### Create Monitoring Alerts

```bash
# Alert if average chunk time increases
gcloud monitoring policies create \
  --display-name="High Indexing Time" \
  --threshold-value=5 \
  --comparison-operator="COMPARISON_GT"

# Alert if success rate drops below 85%
gcloud monitoring policies create \
  --display-name="Low Success Rate" \
  --threshold-value=0.85 \
  --comparison-operator="COMPARISON_LT"
```

## Rollback Instructions

If issues occur during testing:

```bash
# Instant rollback (disable parallelism)
gcloud run jobs update confluence-sync \
  --set-env-vars=GRAPHITI_CONCURRENCY=1 \
  --region=us-central1 \
  --project=ai-knowledge-base-42

# Or disable checkpoints temporarily
# (Requires code change - not exposed as config)

# Clear checkpoint table to start fresh
sqlite3 data/knowledge_base.db "DELETE FROM indexing_checkpoints;"

# Revert Terraform timeouts
git checkout HEAD~1 -- deploy/terraform/staging.tf
git checkout HEAD~1 -- deploy/terraform/cloudrun-jobs.tf
```

## References

- Implementation: `src/knowledge_base/graph/graphiti_indexer.py` (+448 lines)
- Configuration: `src/knowledge_base/config.py` (5 new settings)
- CLI: `src/knowledge_base/cli.py` (--resume flag)
- Database Model: `src/knowledge_base/db/models.py` (IndexingCheckpoint table)
- Tests: `tests/integration/test_intake_pipeline.py`

## Questions?

See the main implementation commit for details:
```bash
git show 929cb72
```
