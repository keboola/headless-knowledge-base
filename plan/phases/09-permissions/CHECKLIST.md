# Phase 09: Permission Checking - Checklist

## Pre-Implementation
- [ ] Read SPEC.md completely
- [ ] Verify Phase 08 is complete
- [ ] Set up Confluence OAuth app
- [ ] Get OAuth client ID and secret
- [ ] Prepare test accounts with different permissions

## Implementation Tasks

### 1. Database Model
- [ ] Add UserLink model to `db/models.py`
- [ ] Run migrations / create table
- [ ] Implement token encryption

### 2. Permission Cache
- [ ] Create `auth/__init__.py`
- [ ] Create `auth/cache.py`
- [ ] Implement Redis caching
- [ ] Add TTL handling
- [ ] Implement cache invalidation

### 3. Permission Checker
- [ ] Create `confluence/permissions.py`
- [ ] Implement `can_access()` method
- [ ] Query Confluence API for permissions
- [ ] Integrate with cache
- [ ] Handle API errors

### 4. Account Linking
- [ ] Create `auth/confluence_link.py`
- [ ] Implement OAuth URL generation
- [ ] Implement callback handler
- [ ] Store encrypted tokens
- [ ] Add unlink capability

### 5. Slack Integration
- [ ] Add "Link Account" button to responses
- [ ] Handle button click action
- [ ] Show linking status
- [ ] Update welcome message

### 6. Search Integration
- [ ] Add user context to search
- [ ] Filter results by permission
- [ ] Handle unlinked users
- [ ] Show appropriate messages

## Post-Implementation
- [ ] Run tests from TEST.md
- [ ] Update PROGRESS.md status to ✅ Done
- [ ] Commit: "feat(phase-09): permission checking"
