# E2E Test Coverage Report

**Generated:** 2026-01-02
**Total Tests:** 77 e2e (73 passing, 0 failing, 4 skipped)

## QA Feedback Implementation Status

Per Senior QA team feedback (`TEST_COVERAGE_FEEDBACK.md`), the following tests were added:

| Recommendation | Status | Implementation |
|----------------|--------|----------------|
| A. Sync Integration Tests | **DONE** | `tests/integration/test_sync_flow.py` (6 tests) |
| B. Search Benchmarking (Golden Dataset) | **DONE** | `tests/integration/test_search_quality.py` (8 tests) |
| C. Security E2E Tests | **DONE** | `tests/e2e/test_security_e2e.py` (7 tests) |
| D. Resilience & Fallback Tests | **DONE** | `tests/e2e/test_resilience.py` (12 tests) |
| E. Load Testing | DOCUMENTED | Use Locust (external tool) |

---

## Test Fix History

**Fixed (2026-01-02)**: All 7 failing tests now pass after the following fixes:

| Fix | Tests Fixed |
|-----|-------------|
| Changed `after_ts` to `parent_ts` - bot replies in threads not channel | 4 tests in `test_e2e_full_flow.py`, 3 in `test_scenarios.py` |
| Export all env vars (`set -a`) - ChromaDB runs in cloud | 3 tests that create knowledge |
| Skip status messages ("Searching...") in `wait_for_bot_reply` | Tests that check response length |
| Fix thread_ts to use `msg_ts` (original message) not reply ts | `test_follow_up_question_in_thread` |

**Files Modified**:
- `tests/e2e/test_e2e_full_flow.py` - Fixed `after_ts` → `parent_ts`
- `tests/e2e/test_scenarios.py` - Fixed `after_ts` → `parent_ts`, fixed thread_ts logic
- `tests/e2e/slack_client.py` - Skip status messages in `wait_for_bot_reply`

---

## Test Files Overview

| File | Tests | Status |
|------|-------|--------|
| **E2E Tests** | | |
| `test_scenarios.py` | 24 | Comprehensive user journey tests |
| `test_e2e_full_flow.py` | 4 | Basic knowledge creation/retrieval |
| `test_feedback_flow.py` | 2 | Feedback lifecycle tests |
| `test_behavioral_signals.py` | 2 | Behavior tracking tests |
| `test_document_workflow.py` | 2 | Document creation/approval tests |
| `test_security_e2e.py` | 7 | Permission & security tests |
| `test_resilience.py` | 12 | Resilience & fallback tests |
| `test_quality_ranking.py` | 3 | Quality-based search ranking tests |
| `test_feedback_modals.py` | 16 | **NEW** - Phase 10.6: Modal feedback + owner notification |
| **Integration Tests** | | |
| `test_document_workflow.py` | 20 | Document approval workflow |
| `test_search_quality.py` | 8 | **NEW** - Golden dataset & BM25 tests |
| `test_sync_flow.py` | 6 | **NEW** - Confluence sync tests |

---

## Detailed Test Coverage

### 1. Knowledge Discovery (`test_scenarios.py::TestKnowledgeDiscovery`)

| Test | Description | Validates |
|------|-------------|-----------|
| `test_new_employee_asks_about_onboarding` | New hire @mentions bot with question | Bot responds with helpful answer (>50 chars) |
| `test_follow_up_question_in_thread` | User asks follow-up in same thread | Bot maintains conversation context |
| `test_question_with_no_relevant_content` | User asks about unknown topic | Bot gracefully handles "I don't know" |

### 2. Knowledge Creation (`test_scenarios.py::TestKnowledgeCreation`)

| Test | Description | Validates |
|------|-------------|-----------|
| `test_quick_fact_creation` | `/create-knowledge` command | Chunk created, quality_score=100 |
| `test_admin_contact_info_creation` | Document system admin contact | Chunk saved with user attribution |
| `test_access_request_info_creation` | Document access request process | Chunk saved and indexed |

### 3. Feedback Loop (`test_scenarios.py::TestFeedbackLoop`)

| Test | Description | Score Impact |
|------|-------------|--------------|
| `test_user_marks_answer_helpful` | User clicks "Helpful" button | +2 points |
| `test_user_marks_answer_outdated` | User clicks "Outdated" button | **-15 points** |
| `test_user_marks_answer_incorrect` | User clicks "Incorrect" button | **-25 points** |

### 4. Behavioral Learning (`test_scenarios.py::TestBehavioralLearning`)

| Test | Description | Signal Value |
|------|-------------|--------------|
| `test_user_says_thanks` | User replies "Thanks!" in thread | +0.4 |
| `test_user_asks_follow_up` | User asks follow-up question (contains ?) | -0.3 |
| `test_user_expresses_frustration` | User says "didn't help", "useless" | -0.5 |
| `test_thumbs_up_reaction` | User adds :thumbsup: emoji | +0.5 |
| `test_thumbs_down_reaction` | User adds :thumbsdown: emoji | -0.5 |

### 5. Quality Ranking (`test_scenarios.py::TestQualityRanking`)

| Test | Description | Validates |
|------|-------------|-----------|
| `test_helpful_content_maintains_ranking` | 3 users mark as helpful | Content stays prominent, feedback_count=3 |
| `test_poor_content_demoted` | 2 users mark as incorrect | Score drops 100 -> 50 |

### 6. Realistic User Journeys (`test_scenarios.py::TestRealisticUserJourneys`)

| Test | Description | Validates |
|------|-------------|-----------|
| `test_new_employee_onboarding_journey` | Full onboarding: ask -> thanks -> follow-up -> create knowledge | Complete workflow |
| `test_knowledge_improvement_cycle` | Old content marked outdated, new content created | New content (100) > Old content (<100) |

### 7. Thread to Knowledge (`test_scenarios.py::TestThreadToKnowledge`)

| Test | Description | Validates |
|------|-------------|-----------|
| `test_save_troubleshooting_thread_as_doc` | Save troubleshooting discussion | Thread context preserved |
| `test_save_decision_thread_as_doc` | Save architectural decision | Decision captured |
| `test_save_onboarding_qa_as_knowledge` | Save onboarding Q&A | Becomes searchable knowledge |

### 8. External Document Ingestion (`test_scenarios.py::TestExternalDocumentIngestion`)

| Test | Description | Status |
|------|-------------|--------|
| `test_ingest_pdf_document` | PDF ingestion via `/ingest-doc` | **SKIPPED** (future feature) |
| `test_ingest_google_doc` | Google Doc ingestion | **SKIPPED** (future feature) |
| `test_ingest_webpage` | Webpage ingestion | **SKIPPED** (future feature) |
| `test_ingest_notion_page` | Notion page ingestion | **SKIPPED** (future feature) |

### 9. Knowledge Admin Escalation (`test_scenarios.py::TestKnowledgeAdminEscalation`)

| Test | Description | Validates |
|------|-------------|-----------|
| `test_offer_admin_help_on_incorrect_feedback` | Incorrect feedback triggers admin help offer | Feedback recorded, admin button shown |
| `test_admin_notification_includes_context` | Admin notification has full context | Query, response, thread link included |
| `test_admin_corrects_and_saves_knowledge` | Admin provides correction | Correction becomes new knowledge |
| `test_repeated_negative_feedback_auto_notifies_admin` | **3+ incorrect reports** | **Auto-notifies admins**, score=25 |

### 10. Quality Ranking Tests (`test_quality_ranking.py`) **NEW**

| Test | Description | Validates |
|------|-------------|-----------|
| `test_high_quality_content_appears_before_low_quality` | Create 2 facts, demote one via feedback | Score mechanism: 100 vs 25, content retrievable |
| `test_demoted_content_excluded_from_results` | Demote content to score 0 | Demotion mechanism works (4x incorrect = 0) |
| `test_helpful_feedback_promotes_content` | Give 5x helpful feedback | Feedback recorded, content appears in response |

**Architecture Note**: Tests verify score CHANGES work correctly. Full ranking verification requires shared database with deployed bot (currently separate DBs).

### 11. Full Flow Tests (`test_e2e_full_flow.py`)

| Test | Description | Validates |
|------|-------------|-----------|
| `test_create_and_retrieve_knowledge` | Create fact, ask bot, verify answer | End-to-end retrieval |
| `test_feedback_improves_score` | Create and retrieve knowledge | Bot finds created content |
| `test_negative_feedback_demotes` | Negative feedback demotion | Content still findable but demoted |
| `test_behavioral_signals` | Thanks in thread (black box) | Interaction completes without error |

### 11. Feedback Flow Tests (`test_feedback_flow.py`)

| Test | Description | Score Journey |
|------|-------------|---------------|
| `test_complete_feedback_lifecycle` | Create -> helpful -> incorrect | 100 -> 100 -> 92 -> 67 |
| `test_feedback_on_multiple_chunks` | Confusing feedback on 2 chunks | Both chunks: 100 -> 95 |

### 12. Behavioral Signals Tests (`test_behavioral_signals.py`)

| Test | Description | Validates |
|------|-------------|-----------|
| `test_behavioral_signals_flow` | Thanks message + thumbsup reaction | Both signals recorded in DB |
| `test_follow_up_signal` | Follow-up question in thread | `has_follow_up=True` on BotResponse |

### 13. Document Workflow Tests (`test_document_workflow.py`)

| Test | Description | Validates |
|------|-------------|-----------|
| `test_manual_document_creation_and_approval` | Create guideline (auto-publish), policy (needs approval) | Approval workflow: draft -> in_review -> approved |
| `test_save_thread_as_doc_flow` | Thread-to-doc with AI drafter | Document created with thread content |

### 14. Enhanced Feedback Modals Tests (`test_feedback_modals.py`) **NEW - Phase 10.6**

#### Modal Builder Tests (`TestFeedbackModalBuilders`)

| Test | Description | Validates |
|------|-------------|-----------|
| `test_incorrect_modal_structure` | Verify incorrect modal fields | callback_id, private_metadata, required fields |
| `test_outdated_modal_structure` | Verify outdated modal fields | callback_id, blocks, metadata structure |
| `test_confusing_modal_structure` | Verify confusing modal fields | callback_id, confusion_block present |

#### Modal Opening Tests (`TestNegativeFeedbackOpensModal`)

| Test | Description | Validates |
|------|-------------|-----------|
| `test_incorrect_feedback_opens_modal` | Click "Incorrect" button | `views_open` called with correct modal |
| `test_outdated_feedback_opens_modal` | Click "Outdated" button | Modal opens with `feedback_outdated_modal` |
| `test_confusing_feedback_opens_modal` | Click "Confusing" button | Modal opens with `feedback_confusing_modal` |
| `test_helpful_feedback_does_not_open_modal` | Click "Helpful" button | Direct submission (no modal) |

#### Modal Submission Tests (`TestModalSubmissionHandlers`)

| Test | Description | Validates |
|------|-------------|-----------|
| `test_incorrect_modal_saves_feedback_with_correction` | Submit incorrect modal | `suggested_correction` field saved |
| `test_outdated_modal_saves_feedback` | Submit outdated modal | Feedback + current info saved |
| `test_confusing_modal_saves_feedback` | Submit confusing modal | Confusion type + clarification saved |

#### Owner Notification Tests (`TestOwnerNotification`)

| Test | Description | Validates |
|------|-------------|-----------|
| `test_get_owner_email_from_governance` | Lookup owner from GovernanceMetadata | Email retrieved via join |
| `test_lookup_slack_user_by_email_success` | Find Slack user by email | `users.lookupByEmail` returns user ID |
| `test_lookup_slack_user_by_email_not_found` | Email not in Slack | Returns None (graceful fallback) |
| `test_notify_owner_success_sends_dm` | Owner found and notified | DM sent to owner's user ID |
| `test_notify_owner_fallback_to_admin_channel` | No owner found | Admin channel receives notification |

#### Full Flow Test (`TestFullFeedbackModalFlow`)

| Test | Description | Validates |
|------|-------------|-----------|
| `test_complete_incorrect_feedback_flow` | Click -> Modal -> Submit -> Notify -> Confirm | Full workflow end-to-end |

---

## Quality Score System

### Explicit Feedback Scores

| Feedback Type | Score Change | Admin Notification |
|---------------|--------------|-------------------|
| Helpful | +2 | No |
| Confusing | -5 | No |
| Outdated | -15 | Offers "Get Admin Help" |
| Incorrect | -25 | Offers "Get Admin Help" |

### Behavioral Signal Scores

| Signal Type | Value | Detection Pattern |
|-------------|-------|-------------------|
| Thanks | +0.4 | "thanks", "thank you", "thx" in reply |
| Positive Reaction | +0.5 | :thumbsup:, :clap:, :heart: emoji |
| Follow-up Question | -0.3 | Contains "?" in thread reply |
| Negative Reaction | -0.5 | :thumbsdown: emoji |
| Frustration | -0.5 | "didn't help", "useless", "wrong" |

### Auto-Escalation Thresholds

| Condition | Action |
|-----------|--------|
| 1 incorrect/outdated feedback | Show "Get Admin Help" button |
| 3+ incorrect feedbacks on same chunk | **Auto-notify @knowledge-admins** |
| Quality score < 50 | Content demoted in search results |

---

## Coverage Gaps & Future Work

### Currently Skipped (Future Features)
- External document ingestion (PDF, Google Doc, Webpage, Notion)

### Recommended Additional Tests
1. **Load testing**: Multiple concurrent users asking questions
2. **Edge cases**: Very long questions, special characters, rate limiting
3. **Integration**: Confluence sync verification
4. **Regression**: Quality score recovery after admin correction

---

## Running the Tests

```bash
# Run all e2e tests
cd /home/coder/Devel/keboola/ai-based-knowledge
source .env.e2e
pytest tests/e2e/ -v

# Run specific test file
pytest tests/e2e/test_scenarios.py -v

# Run specific test class
pytest tests/e2e/test_scenarios.py::TestKnowledgeAdminEscalation -v
```

### Prerequisites
- `.env.e2e` configured with Slack tokens and ChromaDB credentials
- `gcloud auth application-default login` for Vertex AI embeddings
- Deployed bot running on Cloud Run
