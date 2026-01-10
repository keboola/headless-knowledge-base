# Phase 14: Document Creation - Checklist

## Pre-Implementation
- [ ] Read SPEC.md completely
- [ ] Verify Phase 07 (RAG) and Phase 08 (Slack Bot) are complete

## Implementation Tasks

### 1. Database Models
- [ ] Create `documents/__init__.py`
- [ ] Create `documents/models.py`
- [ ] Add Document model
- [ ] Add AreaApprovers model
- [ ] Run migrations

### 2. Area Approvers Config
- [ ] Create seed data for areas (people, finance, engineering, general)
- [ ] Add CLI command to manage approvers
- [ ] Test approver lookup by area

### 3. AI Drafter
- [ ] Create `documents/ai_drafter.py`
- [ ] Implement `draft_from_description()`
- [ ] Implement `draft_from_thread()`
- [ ] Test AI draft quality

### 4. Document Creator
- [ ] Create `documents/creator.py`
- [ ] Implement `create_document()`
- [ ] Implement approval rules by doc_type
- [ ] Implement auto-publish for guideline/information

### 5. Slack Commands
- [ ] Create `slack/doc_commands.py`
- [ ] Implement `/create-doc` command
- [ ] Create document creation modal
- [ ] Handle modal submission
- [ ] Show AI draft preview before final submit

### 6. Thread-to-Doc
- [ ] Implement `save_as_doc` message shortcut
- [ ] Fetch thread messages
- [ ] Generate title + content from thread
- [ ] Pre-fill modal with draft

### 7. Approval Workflow
- [ ] Create `documents/approval.py`
- [ ] Implement `request_approval()`
- [ ] Send DM to approvers with Approve/Reject buttons
- [ ] Handle approve action → publish + index
- [ ] Handle reject action → notify creator
- [ ] Handle edit action → open edit modal

### 8. Indexing
- [ ] Index published documents in ChromaDB
- [ ] Generate embeddings for document content
- [ ] Make documents searchable

### 9. Testing
- [ ] Test create guideline (auto-publish)
- [ ] Test create policy (approval required)
- [ ] Test thread-to-doc conversion
- [ ] Test approval workflow end-to-end
- [ ] Test search finds new documents

## Post-Implementation
- [ ] Run tests from TEST.md
- [ ] Update PROGRESS.md status to ✅ Done
- [ ] Commit: "feat(phase-14): document creation"
