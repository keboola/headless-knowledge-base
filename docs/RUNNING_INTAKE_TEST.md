# Running Intake Pipeline Test on Staging

## Prerequisites

### 1. Authenticate with GCP

```bash
# Login to GCP (opens browser)
gcloud auth login

# Set default project
gcloud config set project ai-knowledge-base-42

# Verify authentication
gcloud config list
```

### 2. Verify Infrastructure Exists

```bash
# Check Cloud Run job exists
gcloud run jobs list --region=us-central1
# Should show: confluence-sync

# Check Neo4j instance exists
gcloud compute instances list --filter="name:neo4j-staging"
# Should show: neo4j-staging  RUNNING

# Check secrets exist
gcloud secrets list
# Should show various secrets like: anthropic-api-key, confluence-api-token, etc.
```

---

## Run Intake Test - Quick Start

### Option 1: Conservative Test (Recommended First)

```bash
./deploy/scripts/run-intake-test.sh --concurrency 3 --space KI
```

**What this does:**
1. Clears Neo4j staging data (MATCH (n) DELETE n)
2. Configures job: `GRAPHITI_CONCURRENCY=3`
3. Executes: `gcloud run jobs execute confluence-sync --wait`
4. Waits for completion
5. Shows results and verification commands

**Expected output:**
```
═══════════════════════════════════════════════════════════
CONFLUENCE INTAKE PIPELINE TEST
═══════════════════════════════════════════════════════════
Project:    ai-knowledge-base-42
Region:     us-central1
Job:        confluence-sync
Space:      KI
Concurrency: 3
Resume:     false

═══════════════════════════════════════════════════════════
STEP 1/4: Clear Neo4j Staging Data
═══════════════════════════════════════════════════════════
...
```

### Option 2: Resume Test (After Interruption)

If the first test was interrupted/timed out:

```bash
# Check how many chunks were indexed
sqlite3 data/knowledge_base.db \
  'SELECT status, COUNT(*) FROM indexing_checkpoints GROUP BY status'

# Resume (skips already-indexed chunks)
./deploy/scripts/run-intake-test.sh --concurrency 3 --space KI --resume --skip-clear
```

### Option 3: Scale Up After Success

If CONCURRENCY=3 succeeds, try higher:

```bash
# 5x concurrency (should be ~2x faster than 3x)
./deploy/scripts/run-intake-test.sh --concurrency 5 --space KI --skip-clear

# 10x concurrency (most aggressive)
./deploy/scripts/run-intake-test.sh --concurrency 10 --space KI --skip-clear
```

---

## Manual Testing (Step-by-Step)

If you prefer manual control instead of the automated script:

### Step 1: Clear Neo4j

```bash
# SSH to staging instance
gcloud compute ssh neo4j-staging --zone=us-central1-a

# Inside instance, delete all data
docker exec neo4j-staging cypher-shell -u neo4j -p <password> \
  "MATCH (n) DETACH DELETE n"

# Verify cleared
docker exec neo4j-staging cypher-shell -u neo4j -p <password> \
  "MATCH (n) RETURN COUNT(n)"
# Should return: 0

# Exit SSH
exit
```

### Step 2: Configure Cloud Run Job

```bash
# Update job environment
gcloud run jobs update confluence-sync \
  --set-env-vars=GRAPHITI_CONCURRENCY=3,GRAPHITI_INTER_CHUNK_DELAY=0.0 \
  --project=ai-knowledge-base-42 \
  --region=us-central1
```

### Step 3: Execute Job

```bash
# Option A: Execute and wait for completion
gcloud run jobs execute confluence-sync \
  --project=ai-knowledge-base-42 \
  --region=us-central1 \
  --wait

# Option B: Execute async (submit and exit)
gcloud run jobs execute confluence-sync \
  --project=ai-knowledge-base-42 \
  --region=us-central1 \
  --async
```

### Step 4: Monitor Progress

```bash
# Real-time logs (while running)
gcloud logging read \
  'resource.type="cloud_run_job" AND resource.labels.job_name="confluence-sync"' \
  --follow \
  --limit=50

# After completion, fetch all logs
gcloud logging read \
  'resource.type="cloud_run_job" AND resource.labels.job_name="confluence-sync"' \
  --limit=100 \
  --format='table(timestamp, textPayload)'
```

---

## Verify Results

After the intake completes, verify success:

### 1. Check Checkpoint Statistics

```bash
sqlite3 data/knowledge_base.db << EOF
SELECT
  status,
  COUNT(*) as count,
  ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM indexing_checkpoints), 2) as percentage
FROM indexing_checkpoints
GROUP BY status;
EOF
```

**Expected output:**
```
indexed|1000|90.9
failed|50|4.5
skipped|50|4.5
```

### 2. Check Success Rate

```bash
sqlite3 data/knowledge_base.db \
  'SELECT ROUND(SUM(CASE WHEN status="indexed" THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) as success_rate FROM indexing_checkpoints'

# Expected: 90+
```

### 3. Check Errors

```bash
sqlite3 data/knowledge_base.db << EOF
SELECT
  error_message,
  COUNT(*) as count
FROM indexing_checkpoints
WHERE status = 'failed'
GROUP BY error_message
LIMIT 10;
EOF
```

### 4. Check Neo4j Has Data

```bash
# SSH to Neo4j instance
gcloud compute ssh neo4j-staging --zone=us-central1-a

# Inside instance, count nodes
docker exec neo4j-staging cypher-shell -u neo4j \
  "MATCH (n) RETURN COUNT(n)"

# Should return: >0 (number of indexed chunks)

# Check by type
docker exec neo4j-staging cypher-shell -u neo4j \
  "MATCH (n) RETURN labels(n) as type, COUNT(*) as count"

# Check episodes (chunks)
docker exec neo4j-staging cypher-shell -u neo4j \
  "MATCH (e:Episode) RETURN e.chunk_id, e.content LIMIT 5"

exit
```

### 5. Measure Performance

Compare the times:

```bash
# Extract from logs
gcloud logging read \
  'resource.type="cloud_run_job" AND resource.labels.job_name="confluence-sync"' \
  --format='value(timestamp)' \
  --limit=1

# First: job start time
# Last: job completion time
# Duration = completion - start

# Expected durations:
# CONCURRENCY=1 (sequential):   60-120 minutes
# CONCURRENCY=3:                20-40 minutes  (3x faster)
# CONCURRENCY=5:                12-24 minutes  (5x faster)
# CONCURRENCY=10:               6-12 minutes   (10x faster)
```

---

## Troubleshooting

### Problem: "gcloud: not found"

**Solution:** Install Google Cloud SDK
```bash
# macOS
brew install --cask google-cloud-sdk

# Linux
curl https://sdk.cloud.google.com | bash
exec -l $SHELL
```

### Problem: "ERROR: (gcloud.run.jobs.execute) User does not have permission"

**Solution:** Ensure you have proper GCP permissions
```bash
# Check current user
gcloud auth list

# Login with correct account
gcloud auth login

# Check project permissions
gcloud projects get-iam-policy ai-knowledge-base-42
```

### Problem: Neo4j SSH access fails

**Solution:** Verify firewall rules
```bash
# Check if SSH is allowed
gcloud compute firewall-rules list --filter="name:neo4j"

# SSH with explicit zone
gcloud compute ssh neo4j-staging --zone=us-central1-a
```

### Problem: Job times out before completing

**Solution:** Reduce concurrency or increase timeout
```bash
# Reduce concurrency
./deploy/scripts/run-intake-test.sh --concurrency 1 --space KI

# OR increase Cloud Run job timeout in Terraform:
# deploy/terraform/staging.tf line 470
# timeout = "28800s"  # 8 hours instead of 6
```

### Problem: High error rate

**Solution:** Check error details
```bash
sqlite3 data/knowledge_base.db \
  'SELECT error_message, COUNT(*) FROM indexing_checkpoints WHERE status="failed" GROUP BY error_message ORDER BY COUNT(*) DESC'

# Common issues:
# - Rate limit errors: Reduce GRAPHITI_CONCURRENCY
# - LLM errors: Check ANTHROPIC_API_KEY is valid
# - Neo4j errors: Check disk space: gcloud compute disks list
# - Connection errors: Check firewall/security rules
```

---

## Complete Testing Workflow

```bash
# 1. Authenticate
gcloud auth login
gcloud config set project ai-knowledge-base-42

# 2. Run conservative test
./deploy/scripts/run-intake-test.sh --concurrency 3 --space KI

# 3. Wait for completion (~20-40 minutes)
# Grab coffee ☕

# 4. Verify results
sqlite3 data/knowledge_base.db 'SELECT status, COUNT(*) FROM indexing_checkpoints GROUP BY status'

# 5. If successful, scale up
./deploy/scripts/run-intake-test.sh --concurrency 5 --space KI --skip-clear

# 6. If interrupted/failed, resume
./deploy/scripts/run-intake-test.sh --concurrency 3 --space KI --resume --skip-clear

# 7. Run CI tests
pytest tests/integration/test_intake_pipeline.py -v

# 8. If all tests pass, you're ready for production!
```

---

## Environment Variables Reference

When running the test script, these env vars are set automatically:

```bash
GRAPHITI_CONCURRENCY=3                 # Concurrent chunks
GRAPHITI_INTER_CHUNK_DELAY=0.0         # No delay with semaphore
GRAPHITI_RATE_LIMIT_THRESHOLD=5        # Circuit breaker: open after 5 failures
GRAPHITI_CIRCUIT_BREAKER_COOLDOWN=60   # Recovery: wait 60 seconds
GRAPHITI_MAX_CONCURRENCY=10            # Safety limit
```

To override:

```bash
export GRAPHITI_CONCURRENCY=10
./deploy/scripts/run-intake-test.sh --space KI
```

---

## Next Steps

After successful intake test:

1. **Run CI tests:**
   ```bash
   pytest tests/integration/test_intake_pipeline.py -v
   ```

2. **Set up monitoring:**
   - Create Cloud Monitoring dashboard
   - Set alerts for success rate drops
   - Set alerts for circuit breaker opens

3. **Deploy to production:**
   - Update production Terraform configs
   - Run full production intake
   - Monitor carefully

4. **Document results:**
   - Compare before/after times
   - Document any issues encountered
   - Share results with team

---

## References

- Implementation: `src/knowledge_base/graph/graphiti_indexer.py`
- CLI: `src/knowledge_base/cli.py`
- Database: `src/knowledge_base/db/models.py`
- Tests: `tests/integration/test_intake_pipeline.py`
- Testing guide: `docs/INTAKE_TESTING.md`

---

## Questions?

Check the commit:
```bash
git show 929cb72  # Performance implementation
git show b00cf39  # Testing infrastructure
git show 186ece7  # End-to-end test script
```
