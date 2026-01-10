# Phase 13: Web UI - Checklist

## Pre-Implementation
- [ ] Read SPEC.md completely
- [ ] Verify Phase 6 (Search API) is complete
- [ ] Verify Phase 12 (Governance) is complete

## Implementation Tasks

### 1. Project Setup
- [ ] Create `web/__init__.py`
- [ ] Create `web/app.py`
- [ ] Create `templates/` directory
- [ ] Create `static/css/` directory
- [ ] Create `static/js/` directory

### 2. Base Template
- [ ] Create `templates/base.html`
- [ ] Add navigation header
- [ ] Add footer
- [ ] Link CSS and JS

### 3. Search Page
- [ ] Create `templates/search.html`
- [ ] Add search form
- [ ] Implement JavaScript fetch
- [ ] Render results with cards
- [ ] Add feedback buttons (thumbs up/down)

### 4. Admin Dashboard
- [ ] Create `templates/admin.html`
- [ ] Show total pages count
- [ ] Show indexed pages count
- [ ] Show last sync time
- [ ] Add "Trigger Sync" button
- [ ] Add "Reindex" button
- [ ] Show task status

### 5. Governance Dashboard
- [ ] Create `templates/governance.html`
- [ ] Show obsolete docs count/list
- [ ] Show documentation gaps
- [ ] Show coverage matrix
- [ ] Show recent issues

### 6. Authentication
- [ ] Implement HTTP Basic Auth
- [ ] Protect `/admin` route
- [ ] Protect `/governance` route
- [ ] Add admin credentials to .env

### 7. Styling
- [ ] Create `static/css/style.css`
- [ ] Style search page
- [ ] Style admin dashboard
- [ ] Style governance dashboard
- [ ] Add responsive breakpoints

### 8. JavaScript
- [ ] Create `static/js/app.js`
- [ ] Implement search form handler
- [ ] Implement result rendering
- [ ] Implement feedback submission
- [ ] Add loading indicators

### 9. Routes
- [ ] Create `web/routes.py`
- [ ] Add route: `GET /` (search)
- [ ] Add route: `GET /admin`
- [ ] Add route: `GET /governance`
- [ ] Mount static files

### 10. Integration
- [ ] Mount web app in main.py
- [ ] Test all API integrations
- [ ] Verify auth works

## Post-Implementation
- [ ] Run tests from TEST.md
- [ ] Update PROGRESS.md status to ✅ Done
- [ ] Commit: "feat(phase-13): web ui"
