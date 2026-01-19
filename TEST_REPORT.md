# Test Report - AI Knowledge Base

**Generated:** 2026-01-11
**Test Runner:** pytest 9.0.2
**Python Version:** 3.11.2
**Platform:** Linux

---

## Executive Summary

| Metric | Value |
|--------|-------|
| **Total Tests** | 401 |
| **Unit Tests** | 272 passed |
| **Integration Tests** | 34 passed |
| **E2E Tests** | 76 passed, 18 failed, 1 skipped |
| **Execution Time** | ~5 min total |

### Overall Status: ISSUES FOUND

The unit and integration tests are solid. **18 E2E tests are failing** with real issues that need attention.

---

## Test Results by Category

### 1. Unit Tests (tests/test_*.py) - ALL PASSING

| File | Tests | Status |
|------|-------|--------|
| test_auth.py | 22 | PASS |
| test_chunking.py | 14 | PASS |
| test_confluence_models.py | 13 | PASS |
| test_db_models.py | 5 | PASS |
| test_documents.py | 44 | PASS |
| test_evaluation.py | 20 | PASS |
| test_governance.py | 21 | PASS |
| test_graph.py | 22 | PASS |
| test_health.py | 3 | PASS |
| test_llm.py | 21 | PASS |
| test_markdown_converter.py | 12 | PASS |
| test_metadata.py | 22 | PASS |
| test_vectorstore.py | 16 | PASS |
| test_web.py | 17 | PASS |

**Unit Test Total: 272/272 PASSED**

### 2. Integration Tests (tests/integration/) - ALL PASSING

| File | Tests | Status |
|------|-------|--------|
| test_document_workflow.py | 20 | PASS |
| test_search_quality.py | 8 | PASS |
| test_sync_flow.py | 6 | PASS |

**Integration Test Total: 34/34 PASSED**

### 3. E2E Tests (tests/e2e/) - 18 FAILURES

| File | Passed | Failed | Status |
|------|--------|--------|--------|
| test_admin_escalation_live.py | 13 | 0 | PASS |
| test_behavioral_signals.py | 2 | 0 | PASS |
| test_document_workflow.py | 2 | 0 | PASS |
| test_e2e_full_flow.py | 3 | 1 | FAIL |
| test_feedback_flow.py | 0 | 2 | FAIL |
| test_feedback_modals.py | 16 | 0 | PASS |
| test_knowledge_creation_live.py | 5 | 0 | PASS |
| test_quality_ranking.py | 0 | 3 | FAIL |
| test_resilience.py | 12 | 0 | PASS |
| test_scenarios.py | 16 | 12 | FAIL |
| test_security_e2e.py | 7 | 0 | PASS |

**E2E Test Total: 76 passed, 18 failed, 1 skipped**

---

## Failed Tests Analysis

### Category 1: Mock `index_single_chunk` Not Being Called (6 tests)

**Affected Tests:**
- `test_complete_feedback_lifecycle`
- `test_quick_fact_creation`
- `test_admin_contact_info_creation`
- `test_access_request_info_creation`
- `test_new_employee_onboarding_journey`

**Error:**
```
AssertionError: Expected 'index_single_chunk' to have been called once. Called 0 times.
```

**Root Cause:** The mock patch path for `VectorIndexer` is incorrect or the code path isn't reaching the indexer.

**Fix Required:** Update mock patch paths in tests or fix the knowledge creation flow to call the indexer.

---

### Category 2: `call_args` is None (11 tests)

**Affected Tests:**
- `test_feedback_on_multiple_chunks`
- `test_high_quality_content_appears_before_low_quality`
- `test_demoted_content_excluded_from_results`
- `test_helpful_feedback_promotes_content`
- `test_user_marks_answer_helpful`
- `test_user_marks_answer_outdated`
- `test_user_marks_answer_incorrect`
- `test_helpful_content_maintains_ranking`
- `test_poor_content_demoted`
- `test_knowledge_improvement_cycle`
- `test_offer_admin_help_on_incorrect_feedback`
- `test_repeated_negative_feedback_auto_notifies_admin`

**Error:**
```
TypeError: 'NoneType' object is not subscriptable
chunk_data = call_args[0][0]
```

**Root Cause:** Mock method was never called, so `call_args` is None.

**Fix Required:** Same as Category 1 - mock paths need updating or code flow needs fixing.

---

### Category 3: Knowledge Retrieval Failure (1 test)

**Test:** `test_create_and_retrieve_knowledge`

**Error:**
```
AssertionError: Bot reply did not contain the secret code. Got: I can't provide you with the secret code for project E2E-0bab02f7...
```

**Root Cause:** Knowledge was created but not indexed properly, so the bot couldn't find it during retrieval.

**Fix Required:** Ensure knowledge chunks are properly indexed in ChromaDB after creation.

---

## Warnings Summary

### Critical Warnings (8 occurrences)
```
RuntimeWarning: coroutine 'AsyncMockMixin._execute_mock_call' was never awaited
```
**Location:** `slack/doc_creation.py` lines 129, 217, 428, 440, 370, 389, 233, 313

**Fix Required:** Use `AsyncMock` with `await` or convert sync calls.

### Deprecation Warnings (25 occurrences)
```
UserWarning: This feature is deprecated as of June 24, 2025
```
**Source:** VertexAI SDK - genai-vertexai-sdk deprecation

**Action:** Plan migration before June 24, 2026.

---

## Root Cause Summary

All 18 failures trace back to **one root issue**:

The `VectorIndexer.index_single_chunk` method is not being called when knowledge is created. This indicates:

1. **Mock patch path mismatch** - Tests mock `knowledge_base.vectorstore.indexer.VectorIndexer` but the actual import might be different
2. **OR** the knowledge creation flow doesn't reach the indexer properly

### Suggested Investigation:

```python
# Check how VectorIndexer is imported in the code being tested
# The mock patch should match the import path exactly

# If code does:
from knowledge_base.vectorstore import VectorIndexer

# Then mock should be:
@patch('module_under_test.VectorIndexer')

# NOT:
@patch('knowledge_base.vectorstore.indexer.VectorIndexer')
```

---

## Passing Test Highlights

### Live Slack Integration - ALL WORKING
- Admin escalation flow
- Feedback buttons
- Bot responses with feedback mechanisms
- Owner notifications

### Security Tests - ALL PASSING
- SQL injection prevention
- XSS prevention
- Permission enforcement
- Data leakage prevention
- Rate limiting

### Resilience Tests - ALL PASSING
- LLM timeout handling
- Rate limit handling
- Provider fallback
- ChromaDB connection failures
- Graceful degradation

---

## Recommendations

### Immediate (P0)
1. **Fix mock paths** for `VectorIndexer` in e2e tests
2. **Verify indexing flow** - ensure `index_single_chunk` is called after knowledge creation
3. **Fix async mock warnings** in `doc_creation.py`

### Short-term (P1)
1. Add integration test for full knowledge creation → indexing → retrieval flow
2. Plan VertexAI SDK migration (deprecation June 2026)

### Long-term (P2)
1. Increase code coverage from 41% to 70%+
2. Add CLI command tests

---

## Test Commands

```bash
# Run all tests with environment
set -a && source .env.e2e && set +a
PYTHONPATH=src .venv/bin/python -m pytest tests/ -v

# Run only failing tests for debugging
set -a && source .env.e2e && set +a
PYTHONPATH=src .venv/bin/python -m pytest tests/e2e/test_scenarios.py::TestKnowledgeCreation -v --tb=long

# Run unit tests only (no env needed)
PYTHONPATH=src .venv/bin/python -m pytest tests/test_*.py -v

# Run with coverage
PYTHONPATH=src .venv/bin/python -m pytest tests/ --cov=src/knowledge_base --cov-report=html
```

---

## Summary Table

| Test Suite | Total | Passed | Failed | Pass Rate |
|------------|-------|--------|--------|-----------|
| Unit | 272 | 272 | 0 | 100% |
| Integration | 34 | 34 | 0 | 100% |
| E2E | 95 | 76 | 18 | 80% |
| **TOTAL** | **401** | **382** | **18** | **95.3%** |

---

*Report generated by Claude Code QA Testing*
