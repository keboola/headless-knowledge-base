#!/bin/bash
# DuckDB Server Startup Script
# This script sets up a DuckDB server on a GCE instance

set -euo pipefail

# Mount the data disk
DATA_DISK="/dev/disk/by-id/google-duckdb-data"
MOUNT_POINT="/data"

# Create mount point
mkdir -p $MOUNT_POINT

# Check if disk is formatted
if ! blkid $DATA_DISK; then
    echo "Formatting data disk..."
    mkfs.ext4 -F $DATA_DISK
fi

# Mount disk
mount $DATA_DISK $MOUNT_POINT

# Add to fstab for persistence
if ! grep -q "$DATA_DISK" /etc/fstab; then
    echo "$DATA_DISK $MOUNT_POINT ext4 defaults 0 2" >> /etc/fstab
fi

# Set permissions
chown -R nobody:nogroup $MOUNT_POINT

# Install Python and DuckDB
apt-get update
apt-get install -y python3 python3-pip python3-venv

# Create virtual environment
python3 -m venv /opt/duckdb-server
source /opt/duckdb-server/bin/activate

# Install DuckDB and FastAPI
pip install duckdb fastapi uvicorn

# Create DuckDB HTTP server script
cat > /opt/duckdb-server/server.py << 'PYTHON'
"""Simple HTTP API for DuckDB."""
import os
import duckdb
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

# Database path
DB_PATH = os.environ.get("DUCKDB_PATH", "/data/knowledge.db")

class QueryRequest(BaseModel):
    query: str
    parameters: list = []

class QueryResponse(BaseModel):
    columns: list
    data: list

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.post("/query")
def execute_query(request: QueryRequest):
    try:
        conn = duckdb.connect(DB_PATH)
        result = conn.execute(request.query, request.parameters)
        columns = [desc[0] for desc in result.description] if result.description else []
        data = result.fetchall()
        conn.close()
        return QueryResponse(columns=columns, data=data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/execute")
def execute_command(request: QueryRequest):
    try:
        conn = duckdb.connect(DB_PATH)
        conn.execute(request.query, request.parameters)
        conn.close()
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
PYTHON

# Create systemd service
cat > /etc/systemd/system/duckdb-server.service << 'SERVICE'
[Unit]
Description=DuckDB HTTP Server
After=network.target

[Service]
Type=simple
User=nobody
Group=nogroup
WorkingDirectory=/opt/duckdb-server
Environment=DUCKDB_PATH=/data/knowledge.db
ExecStart=/opt/duckdb-server/bin/uvicorn server:app --host 0.0.0.0 --port 8080
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE

# Enable and start service
systemctl daemon-reload
systemctl enable duckdb-server
systemctl start duckdb-server

echo "DuckDB server started successfully"
