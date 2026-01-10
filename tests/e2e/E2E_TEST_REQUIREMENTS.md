# E2E Test Requirements & Gap Analysis

## ⚠️ CRITICAL: Real E2E vs Mock Tests

**RULE:** A test is NOT an E2E test if it uses `patch()`, `MagicMock`, or `AsyncMock` for:
- ChromaDB operations
- Slack API calls
- Database writes
- Embedding generation

**Real E2E tests:**
- ✅ Actually call Slack API
- ✅ Actually write to ChromaDB
- ✅ Actually generate embeddings
- ✅ Actually update databases
- ✅ Can be verified manually in Slack/DB

---

## ✅ What IS Tested E2E (Real Tests)

| Feature | Test File | Status |
|---------|-----------|--------|
| Admin escalation to #knowledge-admins | `test_admin_escalation_live.py` | ✅ 5 tests PASS |
| Feedback buttons on bot responses | `test_admin_escalation_live.py` | ✅ 2 tests PASS |
| Feedback flow (button structure) | `test_admin_escalation_live.py` | ✅ 3 tests PASS |
| Information Guardian (feedback mechanisms) | `test_admin_escalation_live.py` | ✅ 3 tests PASS |

**Total Real E2E Tests: 13 tests**

---

## ❌ What is NOT Tested E2E (Uses Mocks!)

### 1. Knowledge Creation (`/create-knowledge`)
**Current:** `test_scenarios.py::TestKnowledgeCreation` - **USES MOCKS**
```python
# BAD - This is NOT an E2E test!
with patch("knowledge_base.slack.quick_knowledge.VectorIndexer") as mock_idx:
    mock_idx.return_value.chroma.upsert = AsyncMock()  # FAKE!
```

**What should be tested:**
- [ ] `/create-knowledge` command works in Slack
- [ ] Content is stored in ChromaDB
- [ ] Embeddings are generated
- [ ] Knowledge is searchable by bot
- [ ] Quality score is initialized to 100.0
- [ ] Metadata (creator, timestamp) is stored

### 2. External Document Ingestion (`/ingest-doc`)
**Current:** `test_scenarios.py::TestExternalDocumentIngestion` - **USES MOCKS**
```python
# BAD - This is NOT an E2E test!
with patch.object(ingester, "_ingest_pdf", new_callable=AsyncMock):
    mock_pdf.return_value = {"status": "success"}  # FAKE!
```

**What should be tested:**
- [ ] `/ingest-doc <url>` works in Slack
- [ ] PDF documents are downloaded and parsed
- [ ] Google Docs are fetched and processed
- [ ] Web pages are scraped and chunked
- [ ] All chunks are stored in ChromaDB
- [ ] Bot can answer questions from ingested docs

### 3. Thread to Knowledge Conversion
**Current:** `test_scenarios.py::TestThreadToKnowledge` - **USES MOCKS**

**What should be tested:**
- [ ] "Save as Doc" shortcut appears in Slack
- [ ] Thread is converted to structured doc
- [ ] Content is indexed in ChromaDB
- [ ] Bot can retrieve knowledge from converted thread

### 4. Feedback Submission & Quality Scores
**Current:** `test_scenarios.py::TestFeedbackLoop` - **USES MOCKS**
```python
# BAD - This is NOT an E2E test!
with patch("knowledge_base.lifecycle.feedback.get_chroma_client"):
    mock_chroma_client.update_quality_score = AsyncMock()  # FAKE!
```

**What should be tested:**
- [ ] User clicks "Helpful" → quality score increases in ChromaDB
- [ ] User clicks "Incorrect" → quality score decreases in ChromaDB
- [ ] User clicks "Outdated" → quality score decreases in ChromaDB
- [ ] User clicks "Confusing" → quality score decreases in ChromaDB
- [ ] Feedback is recorded in analytics DB
- [ ] Quality scores affect search ranking

### 5. Bot Q&A Responses
**Current:** Partially tested in feedback tests

**What should be tested:**
- [ ] Bot responds to @mentions in channels
- [ ] Bot responds to DMs
- [ ] Bot uses conversation history (follow-up questions)
- [ ] Bot provides sources with answers
- [ ] Bot says "I don't know" when no knowledge found
- [ ] Bot handles multi-turn conversations

### 6. Owner Notification
**Current:** Test skipped (email-dependent)

**What should be tested:**
- [ ] Content owner receives DM on negative feedback
- [ ] Admin channel receives fallback if no owner
- [ ] Owner is looked up from ChromaDB metadata

### 7. Document Creation (`/create-doc`)
**Current:** `test_scenarios.py::TestDocumentCreation` - **USES MOCKS**

**What should be tested:**
- [ ] `/create-doc` opens modal in Slack
- [ ] AI generates document based on input
- [ ] Document is stored in ChromaDB
- [ ] Bot can answer questions from created doc

---

## 📋 E2E Test Checklist (Use This ALWAYS)

### Before Marking a Test as "E2E"

- [ ] Does NOT use `@patch` decorator
- [ ] Does NOT use `MagicMock()` or `AsyncMock()`
- [ ] Actually sends messages to Slack (visible in workspace)
- [ ] Actually writes to ChromaDB (can query afterward)
- [ ] Actually writes to databases (can verify with SQL)
- [ ] Can be verified MANUALLY by a human
- [ ] Uses real `slack_client.send_message()`
- [ ] Uses real `VectorIndexer().index_single_chunk()`
- [ ] Uses real `ChromaClient().collection.query()`

### Test Structure Template

```python
@pytest.mark.asyncio
@pytest.mark.e2e
async def test_feature_name_live(
    self,
    slack_client,        # Real Slack client
    e2e_config,         # Real workspace config
    unique_test_id,     # Unique ID per test run
):
    """
    Verify: [What you're testing]

    Flow:
    1. [Action in Slack]
    2. [Verification in DB/ChromaDB]
    3. [Verification in Slack]
    """
    # 1. Perform action
    result = await real_function(real_data)

    # 2. Verify in database
    db_result = await query_database(result.id)
    assert db_result is not None

    # 3. Verify in Slack
    message = await slack_client.wait_for_message(...)
    assert message is not None

    # NO MOCKS! If you use patch(), this is NOT E2E!
```

---

## 🔧 How to Run E2E Tests

### Run All Real E2E Tests
```bash
cd /home/coder/Devel/keboola/ai-based-knowledge
source .venv/bin/activate
set -a && source .env.e2e && set +a

# Run only real E2E tests (no mocks)
pytest tests/e2e/test_admin_escalation_live.py -v
pytest tests/e2e/test_knowledge_creation_live.py -v  # TODO: Create this!
```

### Verify Test is Real E2E
```bash
# Check for mocks - should return NO results for E2E tests
grep -r "patch\|MagicMock\|AsyncMock" tests/e2e/test_admin_escalation_live.py
# Output: (empty) ✅ Good!

# Check for mocks in mock tests
grep -r "patch\|MagicMock\|AsyncMock" tests/e2e/test_scenarios.py
# Output: Many results ❌ These are NOT E2E tests!
```

---

## 📊 Test Coverage Report Format

### After Running Tests, Report:

```markdown
## E2E Test Results - [Date]

### ✅ Passing (Real E2E)
- Admin escalation: 5/5 tests pass
- Feedback buttons: 5/5 tests pass
- Information Guardian: 3/3 tests pass

### ❌ Not E2E Tested (Uses Mocks)
- Knowledge creation: 3 tests (MOCKED)
- Document ingestion: 5 tests (MOCKED)
- Feedback submission: 3 tests (MOCKED)
- Thread conversion: 2 tests (MOCKED)

### 🚧 Failing E2E Tests
- [None]

### 📝 Missing E2E Tests
- Bot Q&A with conversation history
- Quality score updates after feedback
- Owner notification DMs
- Document creation flow
```

---

## 🎯 Priority Order for E2E Test Creation

1. **HIGH PRIORITY** (Core functionality)
   - [ ] Knowledge creation (`/create-knowledge`)
   - [ ] Bot Q&A responses
   - [ ] Feedback submission → quality score updates

2. **MEDIUM PRIORITY** (Important features)
   - [ ] External doc ingestion (`/ingest-doc`)
   - [ ] Thread to knowledge conversion
   - [ ] Owner notification

3. **LOW PRIORITY** (Nice to have)
   - [ ] Document creation (`/create-doc`)
   - [ ] Help command
   - [ ] Admin dashboard (if exists)

---

## 🚨 Failure Reporting Template

When an E2E test fails:

```markdown
## E2E Test Failure Report

**Test:** `test_knowledge_creation_live.py::test_create_knowledge_chunk_directly`
**Date:** 2026-01-09
**Status:** ❌ FAILED

### Error
```
TypeError: VectorIndexer.index_single_chunk() got unexpected keyword argument 'content'
```

### Root Cause
API signature changed - `index_single_chunk()` expects `ChunkData` object, not kwargs

### Impact
- Knowledge creation is BROKEN
- `/create-knowledge` command doesn't work
- Users cannot add knowledge

### Verification
1. Run test: `pytest tests/e2e/test_knowledge_creation_live.py -v`
2. Try in Slack: `/create-knowledge Test fact`
3. Check ChromaDB: `chroma_client.collection.count()`

### Fix Required
Update all calls to use ChunkData object instead of kwargs

### Related Tests
- All knowledge creation tests need updating
- Document ingestion tests may have same issue
```

---

## 📌 Remember

**If you can't verify it manually in Slack or the database, it's NOT an E2E test!**

Mock tests are useful for unit testing, but they don't prove the system works end-to-end.

**Always create BOTH:**
1. Unit tests with mocks (fast, isolated)
2. E2E tests without mocks (slow, comprehensive)

**And always run E2E tests before deploying!**
