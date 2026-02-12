#!/bin/bash
# =============================================================================
# DR Recovery Test
# =============================================================================
# Monthly automated disaster recovery test that:
#   1. Finds the latest READY snapshot of the production Neo4j data disk
#   2. Creates a temporary disk from that snapshot
#   3. Creates a temporary VM with the DR startup script
#   4. Waits for Neo4j to become available
#   5. Validates data integrity via Neo4j HTTP REST API
#   6. Reports PASS/FAIL with all counts
#   7. Cleans up all temporary resources (VM + disk) on exit
#
# Designed to run as a Cloud Run Job on a monthly schedule.
#
# Usage: ./dr-recovery-test.sh
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration (overridable via environment variables)
# ---------------------------------------------------------------------------
PROJECT="${GCP_PROJECT_ID:-ai-knowledge-base-42}"
ZONE="${GCP_ZONE:-us-central1-a}"
PROD_DISK="neo4j-prod-data-disk"
DR_VM="neo4j-dr-test"
DR_DISK="neo4j-dr-test-disk"
DR_PASSWORD="dr-test-$(date +%Y%m%d)"
NETWORK="knowledge-base-vpc"
SUBNET="knowledge-base-subnet"
# Polling configuration
MAX_POLL_ATTEMPTS=30
POLL_INTERVAL=10

# Validation thresholds
MIN_NODES=1000
MIN_RELATIONSHIPS=5000
MIN_ENTITIES=100

# ---------------------------------------------------------------------------
# Cleanup trap — always delete temporary resources on exit
# ---------------------------------------------------------------------------
cleanup() {
    echo ""
    echo "Cleaning up DR test resources..."
    gcloud compute instances delete "${DR_VM}" --project="${PROJECT}" --zone="${ZONE}" --quiet 2>/dev/null || true
    gcloud compute disks delete "${DR_DISK}" --project="${PROJECT}" --zone="${ZONE}" --quiet 2>/dev/null || true
    echo "Cleanup complete."
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# Helper: extract count from Neo4j HTTP REST API JSON response
# ---------------------------------------------------------------------------
extract_count() {
    echo "$1" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['results'][0]['data'][0]['row'][0])"
}

# ---------------------------------------------------------------------------
# Helper: run a Cypher query via Neo4j HTTP REST API
# ---------------------------------------------------------------------------
run_cypher() {
    local query="$1"
    curl -s -u "neo4j:${DR_PASSWORD}" \
        -H "Content-Type: application/json" \
        -d "{\"statements\": [{\"statement\": \"${query}\"}]}" \
        "http://${VM_IP}:7474/db/neo4j/tx/commit"
}

echo "=========================================="
echo "DR Recovery Test"
echo "=========================================="
echo "Project:     ${PROJECT}"
echo "Zone:        ${ZONE}"
echo "Prod Disk:   ${PROD_DISK}"
echo "DR VM:       ${DR_VM}"
echo "DR Disk:     ${DR_DISK}"
echo "=========================================="
echo ""

# ---------------------------------------------------------------------------
# Step 1: Find the latest READY snapshot of the production data disk
# ---------------------------------------------------------------------------
echo "[1/6] Finding latest READY snapshot of ${PROD_DISK}..."

SNAPSHOT_NAME=$(gcloud compute snapshots list \
    --project="${PROJECT}" \
    --filter="sourceDisk~${PROD_DISK} AND status=READY" \
    --sort-by="~creationTimestamp" \
    --limit=1 \
    --format="value(name)")

if [[ -z "${SNAPSHOT_NAME}" ]]; then
    echo "ERROR: No READY snapshot found for disk ${PROD_DISK}"
    echo "Ensure the snapshot schedule policy is active and has run at least once."
    exit 1
fi

echo "  Found snapshot: ${SNAPSHOT_NAME}"

# ---------------------------------------------------------------------------
# Step 2: Create a disk from the snapshot
# ---------------------------------------------------------------------------
echo "[2/6] Creating disk ${DR_DISK} from snapshot ${SNAPSHOT_NAME}..."

gcloud compute disks create "${DR_DISK}" \
    --project="${PROJECT}" \
    --zone="${ZONE}" \
    --source-snapshot="${SNAPSHOT_NAME}" \
    --type="pd-ssd" \
    --quiet

echo "  Disk created."

# ---------------------------------------------------------------------------
# Step 3: Create a temporary VM with the DR startup script
# ---------------------------------------------------------------------------
echo "[3/6] Creating temporary VM ${DR_VM}..."

# Write the DR startup script to a temp file (since this script runs inlined
# in a Cloud Run Job container, we cannot reference external files)
DR_STARTUP_SCRIPT=$(mktemp)
cat > "${DR_STARTUP_SCRIPT}" << 'STARTUP_EOF'
#!/bin/bash
set -euo pipefail

DATA_DISK="/dev/disk/by-id/google-neo4j-dr-data"
MOUNT_POINT="/data"

mkdir -p $MOUNT_POINT

if ! blkid $DATA_DISK; then
    echo "Formatting data disk..."
    mkfs.ext4 -F $DATA_DISK
fi

if ! mountpoint -q $MOUNT_POINT; then
    mount $DATA_DISK $MOUNT_POINT
else
    echo "Data disk already mounted at $MOUNT_POINT"
fi

if ! grep -q "$DATA_DISK" /etc/fstab; then
    echo "$DATA_DISK $MOUNT_POINT ext4 defaults 0 2" >> /etc/fstab
fi

mkdir -p $MOUNT_POINT/neo4j/data $MOUNT_POINT/neo4j/logs $MOUNT_POINT/neo4j/plugins

# Reset auth files so the new NEO4J_AUTH takes effect on restored data
rm -f $MOUNT_POINT/neo4j/data/dbms/auth.ini $MOUNT_POINT/neo4j/data/dbms/auth 2>/dev/null || true

apt-get update
apt-get install -y docker.io
systemctl enable docker
systemctl start docker

NEO4J_PASSWORD=$(curl -sf "http://metadata.google.internal/computeMetadata/v1/instance/attributes/neo4j-password" -H "Metadata-Flavor: Google" 2>/dev/null || echo "dr-test-password")

docker pull neo4j:5.26-community
docker stop neo4j-dr 2>/dev/null || true
docker rm neo4j-dr 2>/dev/null || true

docker run -d \
    --name neo4j-dr \
    --restart always \
    -p 7687:7687 \
    -p 7474:7474 \
    -v $MOUNT_POINT/neo4j/data:/data \
    -v $MOUNT_POINT/neo4j/logs:/logs \
    -e NEO4J_AUTH="neo4j/${NEO4J_PASSWORD}" \
    -e NEO4J_server_memory_heap_initial__size=2G \
    -e NEO4J_server_memory_heap_max__size=4G \
    -e NEO4J_server_memory_pagecache_size=1G \
    -e NEO4J_PLUGINS='["apoc"]' \
    -e NEO4J_dbms_security_procedures_unrestricted='apoc.*' \
    neo4j:5.26-community 2>&1 | tee /tmp/docker-run.log

echo "Neo4j DR test server started successfully"
sleep 5
docker logs neo4j-dr > $MOUNT_POINT/neo4j/docker-startup.log 2>&1 || true
STARTUP_EOF

# Look up the backup-ops service account email
BACKUP_SA=$(gcloud iam service-accounts list \
    --project="${PROJECT}" \
    --filter="email~backup-ops" \
    --format="value(email)" \
    --limit=1)

SA_ARGS=()
if [[ -z "${BACKUP_SA}" ]]; then
    echo "WARNING: backup-ops service account not found, creating VM without explicit SA"
else
    SA_ARGS=("--service-account=${BACKUP_SA}")
fi

gcloud compute instances create "${DR_VM}" \
    --project="${PROJECT}" \
    --zone="${ZONE}" \
    --machine-type="e2-standard-2" \
    --image-family="debian-12" \
    --image-project="debian-cloud" \
    --no-address \
    --network="${NETWORK}" \
    --subnet="${SUBNET}" \
    --tags="neo4j-dr-test" \
    --disk="name=${DR_DISK},device-name=neo4j-dr-data,mode=rw,auto-delete=no" \
    --metadata="neo4j-password=${DR_PASSWORD}" \
    --metadata-from-file="startup-script=${DR_STARTUP_SCRIPT}" \
    --no-restart-on-failure \
    "${SA_ARGS[@]}" \
    --quiet

rm -f "${DR_STARTUP_SCRIPT}"
echo "  VM created."

# ---------------------------------------------------------------------------
# Step 4: Get the VM internal IP and wait for Neo4j
# ---------------------------------------------------------------------------
echo "[4/6] Getting VM internal IP and waiting for Neo4j to start..."

VM_IP=$(gcloud compute instances describe "${DR_VM}" \
    --project="${PROJECT}" \
    --zone="${ZONE}" \
    --format="value(networkInterfaces[0].networkIP)")

echo "  VM internal IP: ${VM_IP}"
echo "  Waiting for Neo4j HTTP API on port 7474 (up to $((MAX_POLL_ATTEMPTS * POLL_INTERVAL))s)..."

for i in $(seq 1 "${MAX_POLL_ATTEMPTS}"); do
    HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
        -u "neo4j:${DR_PASSWORD}" \
        "http://${VM_IP}:7474/" 2>/dev/null || echo "000")

    if [[ "${HTTP_STATUS}" == "200" ]]; then
        echo "  Neo4j is ready (attempt ${i}/${MAX_POLL_ATTEMPTS})"
        break
    fi

    if [[ "${i}" -eq "${MAX_POLL_ATTEMPTS}" ]]; then
        echo "ERROR: Neo4j did not become available within $((MAX_POLL_ATTEMPTS * POLL_INTERVAL)) seconds"
        echo "  Last HTTP status: ${HTTP_STATUS}"
        exit 1
    fi

    echo "  Neo4j not ready (HTTP ${HTTP_STATUS}) - waiting ${POLL_INTERVAL}s (attempt ${i}/${MAX_POLL_ATTEMPTS})..."
    sleep "${POLL_INTERVAL}"
done

# ---------------------------------------------------------------------------
# Step 5: Run validation queries via Neo4j HTTP REST API
# ---------------------------------------------------------------------------
echo "[5/6] Running validation queries..."

# Query: total node count
echo "  Querying total node count..."
RESULT_NODES=$(run_cypher "MATCH (n) RETURN count(n)")
NODE_COUNT=$(extract_count "${RESULT_NODES}")
echo "  Total nodes: ${NODE_COUNT}"

# Query: total relationship count
echo "  Querying total relationship count..."
RESULT_RELS=$(run_cypher "MATCH ()-[r]->() RETURN count(r)")
REL_COUNT=$(extract_count "${RESULT_RELS}")
echo "  Total relationships: ${REL_COUNT}"

# Query: Entity node count
echo "  Querying Entity node count..."
RESULT_ENTITIES=$(run_cypher "MATCH (n:Entity) RETURN count(n)")
ENTITY_COUNT=$(extract_count "${RESULT_ENTITIES}")
echo "  Entity nodes: ${ENTITY_COUNT}"

# Query: Episodic node count (informational)
echo "  Querying Episodic node count..."
RESULT_EPISODIC=$(run_cypher "MATCH (n:Episodic) RETURN count(n)")
EPISODIC_COUNT=$(extract_count "${RESULT_EPISODIC}")
echo "  Episodic nodes: ${EPISODIC_COUNT}"

# ---------------------------------------------------------------------------
# Step 6: Report PASS/FAIL
# ---------------------------------------------------------------------------
echo ""
echo "[6/6] Validation Results"
echo "=========================================="

PASS=true

if [[ "${NODE_COUNT}" -gt "${MIN_NODES}" ]]; then
    echo "  PASS: Total nodes (${NODE_COUNT}) > ${MIN_NODES}"
else
    echo "  FAIL: Total nodes (${NODE_COUNT}) <= ${MIN_NODES}"
    PASS=false
fi

if [[ "${REL_COUNT}" -gt "${MIN_RELATIONSHIPS}" ]]; then
    echo "  PASS: Total relationships (${REL_COUNT}) > ${MIN_RELATIONSHIPS}"
else
    echo "  FAIL: Total relationships (${REL_COUNT}) <= ${MIN_RELATIONSHIPS}"
    PASS=false
fi

if [[ "${ENTITY_COUNT}" -gt "${MIN_ENTITIES}" ]]; then
    echo "  PASS: Entity nodes (${ENTITY_COUNT}) > ${MIN_ENTITIES}"
else
    echo "  FAIL: Entity nodes (${ENTITY_COUNT}) <= ${MIN_ENTITIES}"
    PASS=false
fi

echo "  INFO: Episodic nodes: ${EPISODIC_COUNT}"
echo "=========================================="

if [[ "${PASS}" == "true" ]]; then
    echo "DR RECOVERY TEST: PASS"
    echo "=========================================="
    exit 0
else
    echo "DR RECOVERY TEST: FAIL"
    echo "=========================================="
    exit 1
fi
