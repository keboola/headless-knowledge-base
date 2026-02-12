#!/bin/bash
# =============================================================================
# Sync Production Neo4j Data to Staging
# =============================================================================
# This script refreshes staging Neo4j with production data by:
#   1. Finding the latest READY snapshot of the production data disk
#   2. Stopping the staging VM
#   3. Detaching and deleting the old staging data disk
#   4. Creating a new disk from the production snapshot (same name)
#   5. Attaching the new disk and starting the staging VM
#   6. Validating Neo4j starts successfully
#
# All operations use gcloud compute API calls (no SSH required).
# Designed to run as a Cloud Run Job on a nightly schedule.
#
# Usage: ./sync-prod-to-staging.sh
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PROJECT="${GCP_PROJECT_ID:-ai-knowledge-base-42}"
ZONE="${GCP_ZONE:-us-central1-a}"
PROD_DISK="neo4j-prod-data-disk"
STAGING_VM="neo4j-staging"
DISK_NAME="neo4j-staging-data-disk"
DEVICE_NAME="neo4j-staging-data"
MAX_BOOT_ATTEMPTS=18
BOOT_POLL_INTERVAL=10

echo "=========================================="
echo "Production -> Staging Neo4j Data Refresh"
echo "=========================================="
echo "Project:     ${PROJECT}"
echo "Zone:        ${ZONE}"
echo "Prod Disk:   ${PROD_DISK}"
echo "Staging VM:  ${STAGING_VM}"
echo "Target Disk: ${DISK_NAME}"
echo "=========================================="
echo ""

# ---------------------------------------------------------------------------
# Step 1: Find the latest READY snapshot of the production data disk
# ---------------------------------------------------------------------------
echo "[1/7] Finding latest READY snapshot of ${PROD_DISK}..."

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
# Step 2: Stop the staging VM
# ---------------------------------------------------------------------------
echo "[2/7] Stopping staging VM ${STAGING_VM}..."

gcloud compute instances stop "${STAGING_VM}" \
    --project="${PROJECT}" \
    --zone="${ZONE}" \
    --quiet

echo "  VM stopped."

# ---------------------------------------------------------------------------
# Step 3: Detach the old data disk (may not exist on first run)
# ---------------------------------------------------------------------------
echo "[3/7] Detaching old data disk ${DISK_NAME} from ${STAGING_VM}..."

gcloud compute instances detach-disk "${STAGING_VM}" \
    --project="${PROJECT}" \
    --zone="${ZONE}" \
    --disk="${DISK_NAME}" \
    --quiet || true

echo "  Disk detached (or was not attached)."

# ---------------------------------------------------------------------------
# Step 4: Delete the old data disk (may not exist on first run)
# ---------------------------------------------------------------------------
echo "[4/7] Deleting old data disk ${DISK_NAME}..."

gcloud compute disks delete "${DISK_NAME}" \
    --project="${PROJECT}" \
    --zone="${ZONE}" \
    --quiet || true

echo "  Disk deleted (or did not exist)."

# ---------------------------------------------------------------------------
# Step 5: Create new disk from the production snapshot
# ---------------------------------------------------------------------------
echo "[5/7] Creating new disk ${DISK_NAME} from snapshot ${SNAPSHOT_NAME}..."

gcloud compute disks create "${DISK_NAME}" \
    --project="${PROJECT}" \
    --zone="${ZONE}" \
    --source-snapshot="${SNAPSHOT_NAME}" \
    --type="pd-ssd" \
    --quiet

echo "  Disk created."

# ---------------------------------------------------------------------------
# Step 6: Attach the new disk and start the staging VM
# ---------------------------------------------------------------------------
echo "[6/7] Attaching disk ${DISK_NAME} to ${STAGING_VM}..."

gcloud compute instances attach-disk "${STAGING_VM}" \
    --project="${PROJECT}" \
    --zone="${ZONE}" \
    --disk="${DISK_NAME}" \
    --device-name="${DEVICE_NAME}" \
    --mode=rw \
    --quiet

echo "  Disk attached."

echo "  Starting staging VM ${STAGING_VM}..."

gcloud compute instances start "${STAGING_VM}" \
    --project="${PROJECT}" \
    --zone="${ZONE}" \
    --quiet

echo "  VM start command issued."

# ---------------------------------------------------------------------------
# Step 7: Validate VM is running and Neo4j starts successfully
# ---------------------------------------------------------------------------
echo "[7/7] Waiting for VM to reach RUNNING status and Neo4j to start..."

# Wait for VM to reach RUNNING status
for i in $(seq 1 "${MAX_BOOT_ATTEMPTS}"); do
    VM_STATUS=$(gcloud compute instances describe "${STAGING_VM}" \
        --project="${PROJECT}" \
        --zone="${ZONE}" \
        --format="value(status)")

    if [[ "${VM_STATUS}" == "RUNNING" ]]; then
        echo "  VM is RUNNING (attempt ${i}/${MAX_BOOT_ATTEMPTS})"
        break
    fi

    if [[ "${i}" -eq "${MAX_BOOT_ATTEMPTS}" ]]; then
        echo "ERROR: VM did not reach RUNNING status within $((MAX_BOOT_ATTEMPTS * BOOT_POLL_INTERVAL)) seconds"
        echo "  Current status: ${VM_STATUS}"
        exit 1
    fi

    echo "  VM status: ${VM_STATUS} - waiting ${BOOT_POLL_INTERVAL}s (attempt ${i}/${MAX_BOOT_ATTEMPTS})..."
    sleep "${BOOT_POLL_INTERVAL}"
done

# Check serial port output for Neo4j startup confirmation
echo "  Checking serial port for Neo4j startup confirmation..."
NEO4J_STARTED=false

for i in $(seq 1 "${MAX_BOOT_ATTEMPTS}"); do
    SERIAL_OUTPUT=$(gcloud compute instances get-serial-port-output "${STAGING_VM}" \
        --project="${PROJECT}" \
        --zone="${ZONE}" \
        --port=1 2>/dev/null || echo "")

    if echo "${SERIAL_OUTPUT}" | grep -q "Neo4j staging server started successfully"; then
        NEO4J_STARTED=true
        echo "  Neo4j startup confirmed via serial port (attempt ${i}/${MAX_BOOT_ATTEMPTS})"
        break
    fi

    if [[ "${i}" -eq "${MAX_BOOT_ATTEMPTS}" ]]; then
        echo "WARNING: Neo4j startup message not found in serial port output after $((MAX_BOOT_ATTEMPTS * BOOT_POLL_INTERVAL)) seconds"
        echo "  The VM is running but Neo4j may still be starting."
        echo "  Check manually: gcloud compute instances get-serial-port-output ${STAGING_VM} --zone=${ZONE} --project=${PROJECT}"
        break
    fi

    echo "  Neo4j not yet started - waiting ${BOOT_POLL_INTERVAL}s (attempt ${i}/${MAX_BOOT_ATTEMPTS})..."
    sleep "${BOOT_POLL_INTERVAL}"
done

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "=========================================="
echo "Production -> Staging Refresh Complete"
echo "=========================================="
echo "Snapshot used: ${SNAPSHOT_NAME}"
echo "Disk created:  ${DISK_NAME}"
echo "VM status:     ${VM_STATUS}"
echo "Neo4j started: ${NEO4J_STARTED}"
echo "=========================================="

exit 0
