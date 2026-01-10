# Phase 10.5: Behavioral Signals - Checklist

## Pre-Implementation
- [ ] Read SPEC.md completely
- [ ] Verify Phase 10 is complete

## Implementation Tasks

### 1. Database Model
- [ ] Add BehavioralSignal model
- [ ] Run migrations / create table

### 2. Signal Analyzer
- [ ] Create `feedback/signal_analyzer.py`
- [ ] Define gratitude patterns
- [ ] Define frustration patterns
- [ ] Define question patterns
- [ ] Implement `is_gratitude()`
- [ ] Implement `is_frustration()`
- [ ] Implement `is_follow_up_question()`

### 3. Behavior Tracker
- [ ] Create `feedback/behavior_tracker.py`
- [ ] Implement `on_bot_response()`
- [ ] Implement `on_thread_message()`
- [ ] Implement `on_reaction_added()`
- [ ] Implement `check_timeout()`
- [ ] Implement `record_signal()`

### 4. Response Tracking
- [ ] Link bot messages to response IDs
- [ ] Cache thread_ts → response_id mapping
- [ ] Handle multiple responses in thread

### 5. Slack Events
- [ ] Subscribe to `message` events
- [ ] Subscribe to `reaction_added` events
- [ ] Filter to relevant events only

### 6. Timeout Management
- [ ] Schedule timeout checks
- [ ] Cancel on user activity
- [ ] Clean up completed tasks

## Post-Implementation
- [ ] Run tests from TEST.md
- [ ] Update PROGRESS.md status to ✅ Done
- [ ] Commit: "feat(phase-10.5): behavioral signals"
