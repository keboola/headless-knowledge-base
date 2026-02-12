#!/bin/bash
# =============================================================================
# Neo4j DR Test Server Startup Script
# =============================================================================
# Based on the production startup script, adapted for disaster recovery testing.
# Key differences from production:
#   - Device name: neo4j-dr-data (not neo4j-prod-data)
#   - Auth reset: removes existing auth files so DR_PASSWORD takes effect
#   - Container name: neo4j-dr (not neo4j-prod)
# =============================================================================

set -euo pipefail

# Mount the data disk (restored from production snapshot)
DATA_DISK="/dev/disk/by-id/google-neo4j-dr-data"
MOUNT_POINT="/data"

# Create mount point
mkdir -p $MOUNT_POINT

# Check if disk is formatted
if ! blkid $DATA_DISK; then
    echo "Formatting data disk..."
    mkfs.ext4 -F $DATA_DISK
fi

# Mount disk only if not already mounted
if ! mountpoint -q $MOUNT_POINT; then
    mount $DATA_DISK $MOUNT_POINT
else
    echo "Data disk already mounted at $MOUNT_POINT"
fi

# Add to fstab for persistence
if ! grep -q "$DATA_DISK" /etc/fstab; then
    echo "$DATA_DISK $MOUNT_POINT ext4 defaults 0 2" >> /etc/fstab
fi

# Create Neo4j directories
mkdir -p $MOUNT_POINT/neo4j/data
mkdir -p $MOUNT_POINT/neo4j/logs
mkdir -p $MOUNT_POINT/neo4j/plugins

# Reset auth files so the new NEO4J_AUTH takes effect on restored data
# (production snapshot has its own auth credentials baked in)
rm -f $MOUNT_POINT/neo4j/data/dbms/auth.ini $MOUNT_POINT/neo4j/data/dbms/auth 2>/dev/null || true

# Install Docker
apt-get update
apt-get install -y docker.io
systemctl enable docker
systemctl start docker

# Retrieve Neo4j password from metadata server (with error handling)
NEO4J_PASSWORD=$(curl -sf "http://metadata.google.internal/computeMetadata/v1/instance/attributes/neo4j-password" -H "Metadata-Flavor: Google" 2>/dev/null || echo "dr-test-password")
echo "NEO4J_PASSWORD set to: ${NEO4J_PASSWORD:0:8}***"

# Pull and run Neo4j
docker pull neo4j:5.26-community

# Stop any existing container
docker stop neo4j-dr 2>/dev/null || true
docker rm neo4j-dr 2>/dev/null || true

# Run Neo4j container - DR test configuration
# Same JVM memory and APOC settings as production
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

# Log docker container status for debugging
sleep 5
docker logs neo4j-dr > $MOUNT_POINT/neo4j/docker-startup.log 2>&1 || true
docker inspect neo4j-dr >> $MOUNT_POINT/neo4j/docker-startup.log 2>&1 || true
