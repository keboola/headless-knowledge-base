# Phase 3: Search Integration - Verification

## How to Verify

### 1. Search with Graph OFF
Run:
```bash
python -m src.knowledge_base.cli search "query" --no-graph
```
**Expected**: Returns standard results.

### 2. Search with Graph ON
Run:
```bash
python -m src.knowledge_base.cli search "query" --graph
```
**Expected**: Returns results, potentially distinct from OFF if graph connections exist. Logs should indicate graph retrieval was attempted.

### 3. Compare Results
Verify that graph results are effectively merged (e.g., a document found *only* via graph traversal appears in the final list).
