# Phase 08: Slack Bot - Checklist

## Pre-Implementation
- [ ] Read SPEC.md completely
- [ ] Verify Phase 07 is complete
- [ ] Create Slack App in workspace
- [ ] Get SLACK_BOT_TOKEN
- [ ] Get SLACK_APP_TOKEN
- [ ] Get SLACK_SIGNING_SECRET
- [ ] Add credentials to `.env`

## Implementation Tasks

### 1. Slack App Setup
- [ ] Create `slack/__init__.py`
- [ ] Create `slack/app.py`
- [ ] Initialize AsyncApp with credentials
- [ ] Create request handler

### 2. Command Handler
- [ ] Create `slack/commands.py`
- [ ] Implement `/ask` command
- [ ] Add acknowledgment
- [ ] Show typing indicator
- [ ] Return RAG response

### 3. Event Handlers
- [ ] Create `slack/events.py`
- [ ] Implement `app_mention` handler
- [ ] Implement DM message handler
- [ ] Extract query from text
- [ ] Reply in threads

### 4. Message Formatting
- [ ] Create `slack/messages.py`
- [ ] Format answer with markdown
- [ ] Format source links
- [ ] Add freshness indicators
- [ ] Add feedback buttons

### 5. FastAPI Integration
- [ ] Add `/slack/events` endpoint
- [ ] Add `/slack/commands` endpoint
- [ ] Add `/slack/interactions` endpoint
- [ ] Configure URL in Slack app

### 6. Slack App Configuration
- [ ] Set Request URL for events
- [ ] Set Request URL for commands
- [ ] Add required OAuth scopes
- [ ] Install app to workspace

## Post-Implementation
- [ ] Run tests from TEST.md
- [ ] Update PROGRESS.md status to ✅ Done
- [ ] Commit: "feat(phase-08): slack bot"
