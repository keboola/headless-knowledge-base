#!/bin/bash
# Neo4j Production Server Startup Script
# This script sets up a Neo4j server on a GCE instance using Docker

set -euo pipefail

# Mount the data disk
DATA_DISK="/dev/disk/by-id/google-neo4j-prod-data"
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

# Retrieve Neo4j password from Secret Manager
NEO4J_PASSWORD=$(gcloud secrets versions access latest --secret="neo4j-password")

# Pull and run Neo4j
docker pull neo4j:5.26-community

# Stop any existing container
docker stop neo4j-prod 2>/dev/null || true
docker rm neo4j-prod 2>/dev/null || true

# Run Neo4j container
# Note: We expose 7687 (Bolt) and 7474 (HTTP)
# We configure Bolt to listen on all interfaces.
docker run -d \
    --name neo4j-prod \
    --restart always \
    -p 7687:7687 \
    -p 7474:7474 \
    -v $MOUNT_POINT/neo4j/data:/data \
    -v $MOUNT_POINT/neo4j/logs:/logs \
    -v $MOUNT_POINT/neo4j/plugins:/plugins \
    -e NEO4J_AUTH="neo4j/${NEO4J_PASSWORD}" \
    -e NEO4J_server_memory_heap_initial_size=2G \
    -e NEO4J_server_memory_heap_max_size=4G \
    -e NEO4J_server_memory_pagecache_size=2G \
    -e NEO4J_server_bolt_listen_address=0.0.0.0:7687 \
    -e NEO4J_server_bolt_advertised_address=neo4j.internal.keboola.com:443 \
    -e NEO4J_server_bolt_tls_level=DISABLED \
    -e NEO4J_server_http_listen_address=0.0.0.0:7474 \
    -e NEO4J_server_http_allowed_origins="*" \
    neo4j:5.26-community 2>&1 | tee /tmp/docker-run.log

echo "Neo4j production server started successfully"

# Log docker container status for debugging
sleep 5
docker logs neo4j-prod > $MOUNT_POINT/neo4j/docker-startup.log 2>&1 || true
docker inspect neo4j-prod >> $MOUNT_POINT/neo4j/docker-startup.log 2>&1 || true
