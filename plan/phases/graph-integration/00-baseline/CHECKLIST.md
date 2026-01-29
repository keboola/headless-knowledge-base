# Phase 0: Baseline & Spike - Checklist

## Baseline
- [ ] Create `tests/data/baseline_queries.json` with 20-30 diverse queries (Simple, Multi-hop, Entity).
- [ ] Implement `scripts/measure_baseline.py` to run queries against current system and log metrics.
- [ ] Run baseline measurement and save report to `docs/AGENT-REPORTS/baseline_retrieval_v1.md`.

## Spike Implementation
- [ ] Create `scripts/spike_graphiti.py`.
- [ ] Configure local Kuzu instance.
- [ ] Ingest 100 sample documents into Graphiti/Kuzu.
- [ ] Implement simple search/traversal in the spike script.

## Comparison & Analysis
- [ ] Run extraction comparison on 50 docs.
- [ ] Analyze results:
    - [ ] Compare entity types.
    - [ ] Compare disambiguation.
    - [ ] Calculate cost per document.
- [ ] Document findings in `docs/AGENT-REPORTS/graphiti_spike_results.md`.

## Decision Gate
- [ ] Review all metrics.
- [ ] Confirm "Go/No-Go" for full implementation.
