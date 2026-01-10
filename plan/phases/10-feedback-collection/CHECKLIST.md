# Phase 10: Feedback Collection - Checklist

## Pre-Implementation
- [ ] Read SPEC.md completely
- [ ] Verify Phase 08 is complete

## Implementation Tasks

### 1. Database Model
- [ ] Create `feedback/__init__.py`
- [ ] Create `feedback/models.py`
- [ ] Add Feedback model
- [ ] Run migrations / create table

### 2. Response Tracking
- [ ] Generate unique response_id per answer
- [ ] Store response context (query, docs)
- [ ] Cache for button callback lookup

### 3. Feedback Buttons
- [ ] Create button blocks
- [ ] Add to all bot responses
- [ ] Include response_id in value

### 4. Button Handlers
- [ ] Create `slack/interactions.py`
- [ ] Handle `feedback_positive`
- [ ] Handle `feedback_negative`
- [ ] Handle `feedback_partial`
- [ ] Handle `feedback_suggest`

### 5. Modals
- [ ] Create negative feedback modal
- [ ] Create suggestion modal
- [ ] Handle modal submissions
- [ ] Store detailed feedback

### 6. UI Updates
- [ ] Update message after feedback
- [ ] Show "Thanks for feedback"
- [ ] Disable buttons after click

### 7. Feedback Collector
- [ ] Create `feedback/collector.py`
- [ ] Implement `record()` method
- [ ] Link feedback to documents

## Post-Implementation
- [ ] Run tests from TEST.md
- [ ] Update PROGRESS.md status to ✅ Done
- [ ] Commit: "feat(phase-10): feedback collection"
