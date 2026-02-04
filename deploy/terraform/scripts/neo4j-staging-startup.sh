#!/bin/bash
# Neo4j Staging Server Startup Script
# This script sets up a Neo4j server on a GCE instance using Docker

set -euo pipefail

# Log all output to a file for debugging
LOG_FILE="/var/log/neo4j-startup.log"
exec 1> >(tee -a "$LOG_FILE")
exec 2>&1

# Mount the data disk
DATA_DISK="/dev/disk/by-id/google-neo4j-staging-data"
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

# Install Docker
apt-get update
apt-get install -y docker.io
systemctl enable docker
systemctl start docker

# Get Neo4j password from metadata
NEO4J_PASSWORD=$(curl -s "http://metadata.google.internal/computeMetadata/v1/instance/attributes/neo4j-password" -H "Metadata-Flavor: Google" 2>/dev/null || echo "staging-password")
echo "NEO4J_PASSWORD set to: ${NEO4J_PASSWORD:0:8}***" # Log first 8 chars for debugging

# Pull and run Neo4j
docker pull neo4j:5.26-community

# Stop any existing container
docker stop neo4j-staging 2>/dev/null || true
docker rm neo4j-staging 2>/dev/null || true

# Run Neo4j container - add advertised_address
docker run -d \
    --name neo4j-staging \
    --restart always \
    -p 7687:7687 \
    -p 7474:7474 \
    -v $MOUNT_POINT/neo4j/data:/data \
    -e NEO4J_AUTH="neo4j/${NEO4J_PASSWORD}" \
    -e NEO4J_server_bolt_advertised_address=neo4j.staging.keboola.dev:443 \
    neo4j:5.26-community 2>&1 | tee /tmp/docker-run.log

echo "Neo4j staging server started successfully"
echo "Bolt endpoint: bolt://$(hostname -I | awk '{print $1}'):7687"

# Log docker container status for debugging
sleep 5
docker logs neo4j-staging > $MOUNT_POINT/neo4j/docker-startup.log 2>&1 || true
docker inspect neo4j-staging >> $MOUNT_POINT/neo4j/docker-startup.log 2>&1 || true
