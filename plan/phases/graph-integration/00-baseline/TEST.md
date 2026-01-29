# Phase 0: Baseline & Spike - Verification

## How to Verify

### 1. Baseline Measurement
Run the measurement script:
```bash
python scripts/measure_baseline.py
```
**Expected Output**: A Markdown table showing Recall@K, Precision, and Latency for the current system.

### 2. Graphiti Spike
Run the spike script:
```bash
python scripts/spike_graphiti.py
```
**Expected Output**:
- Successful ingestion of 100 docs without errors.
- Successful execution of graph queries.
- Latency logs showing performance < 500ms for queries.

### 3. Extraction Quality
Review the generated report `docs/AGENT-REPORTS/graphiti_spike_results.md`.
**Verify**:
- Graphiti extracts relevant entities.
- Cost is within acceptable limits.
