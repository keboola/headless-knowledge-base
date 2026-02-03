#!/bin/bash
# Neo4j Staging Server Startup Script
# This script sets up a Neo4j server on a GCE instance using Docker

set -euo pipefail

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
NEO4J_PASSWORD=$(curl -s "http://metadata.google.internal/computeMetadata/v1/instance/attributes/neo4j-password" -H "Metadata-Flavor: Google" || echo "staging-password")

# Pull and run Neo4j
docker pull neo4j:5.26-community

# Stop any existing container
docker stop neo4j-staging 2>/dev/null || true
docker rm neo4j-staging 2>/dev/null || true

# Run Neo4j container
docker run -d \
    --name neo4j-staging \
    --restart always \
    -p 7687:7687 \
    -p 7474:7474 \
    -v $MOUNT_POINT/neo4j/data:/data \
    -v $MOUNT_POINT/neo4j/logs:/logs \
    -v $MOUNT_POINT/neo4j/plugins:/plugins \
    -e NEO4J_AUTH="neo4j/${NEO4J_PASSWORD}" \
    -e NEO4J_PLUGINS='["apoc"]' \
    -e NEO4J_dbms_security_procedures_unrestricted='apoc.*' \
    -e NEO4J_server_memory_heap_initial__size=512M \
    -e NEO4J_server_memory_heap_max__size=1G \
    -e NEO4J_server_memory_pagecache_size=512M \
    -e NEO4J_server_http_listen__address=:7474 \
    -e NEO4J_server_bolt_listen__address=:7687 \
    -e NEO4J_server_bolt_advertised__address=neo4j.staging.keboola.dev:443 \
    -e NEO4J_server_bolt_tls__level=DISABLED \
    -e NEO4J_server_http_allowed__origins="*" \
    neo4j:5.26-community

echo "Neo4j staging server started successfully"
echo "Bolt endpoint: bolt://$(hostname -I | awk '{print $1}'):7687"
