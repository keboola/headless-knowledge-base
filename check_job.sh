#!/bin/bash
gcloud run jobs executions list --job=confluence-sync-staging --region=us-central1 --project=ai-knowledge-base-42 --limit=1
