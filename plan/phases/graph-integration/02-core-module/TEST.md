# Phase 2: Core Graph Module - Verification

## How to Verify

### 1. Unit Tests
Run:
```bash
pytest tests/unit/test_graphiti_components.py
```
(You will need to create this test file).

### 2. Integration Test (Local Kuzu)
Create a temporary script `scripts/test_graph_flow.py`:
1.  Initialize Builder.
2.  Ingest 1 dummy document.
3.  Initialize Retriever.
4.  Search for an entity in that document.
5.  Assert results are found.

Run:
```bash
python scripts/test_graph_flow.py
```
**Expected**: No errors, valid search results printed.
