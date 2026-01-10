# E2E Testing Guide

## ⚠️ CRITICAL: Always Test E2E Before Deploying

**Rule:** If it's not tested E2E, it's not tested at all.

Mock tests prove your mocks work. E2E tests prove your **system** works.

---

## 📖 Quick Start

### Run All E2E Tests

```bash
cd /home/coder/Devel/keboola/ai-based-knowledge
./run_e2e_tests.sh
```

This will:
1. Run all real E2E tests (no mocks)
2. Generate a detailed report
3. Show what's NOT tested
4. Exit with error if any test fails

### Current Test Results

```bash
# Run and see what works
./run_e2e_tests.sh

# Expected output:
# ✅ Admin Escalation & Info Guardian: PASSED (13 tests)
# ❌ Knowledge Creation: NOT TESTED (uses mocks)
# ❌ Doc Ingestion: NOT TESTED (uses mocks)
```

---

## 📊 What's Tested vs What's NOT

See detailed reports:
- `E2E_TEST_REPORT.md` - Current coverage
- `E2E_TEST_REQUIREMENTS.md` - What needs testing

**Summary:**
- ✅ 13 real E2E tests passing
- ❌ ~18 mock tests (NOT real E2E)
- 📊 E2E Coverage: ~42%

---

## 🚨 How to Spot Fake E2E Tests

### ❌ FAKE (Uses Mocks)

```python
with patch("VectorIndexer") as mock:
    mock.return_value.chroma.upsert = AsyncMock()  # FAKE!
```

### ✅ REAL (No Mocks)

```python
indexer = VectorIndexer()  # Real class
await indexer.index_single_chunk(chunk)  # Real call
```

**If it has `patch()`, `MagicMock()`, or `AsyncMock()` → NOT E2E!**

---

## 📝 Always Report Failures

When E2E test fails, report using this template:

```markdown
## E2E Failure Report

**Test:** test_name
**Date:** YYYY-MM-DD
**Error:** [paste error]

**Verified Manually:**
- [ ] Tried in Slack: [works/broken]
- [ ] Checked ChromaDB: [has data/empty]
- [ ] Checked logs: [error/ok]

**Impact:** [describe user impact]
**Fix:** [what needs fixing]
```

Save to: `e2e_failures/YYYY-MM-DD_test_name.md`

---

## 🎯 Key Files

- `README.md` (this file) - Quick guide
- `E2E_TEST_REPORT.md` - Current coverage
- `E2E_TEST_REQUIREMENTS.md` - Detailed requirements
- `run_e2e_tests.sh` - Run all tests
- `test_admin_escalation_live.py` - Example real E2E tests

---

## ✅ Remember

**No mocks = Real E2E test**
**Has mocks = NOT E2E test**

Always verify manually in Slack or database!
