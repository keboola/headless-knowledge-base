# Phase 12: Governance Reports - Checklist

## Pre-Implementation
- [ ] Read SPEC.md completely
- [ ] Verify Phase 11 is complete

## Implementation Tasks

### 1. Database Models
- [ ] Create `governance/__init__.py`
- [ ] Add GovernanceIssue model
- [ ] Run migrations

### 2. Obsolete Detector
- [ ] Create `governance/obsolete_detector.py`
- [ ] Implement age-based detection
- [ ] Implement quality-based detection
- [ ] Implement feedback-based detection
- [ ] Implement engagement-based detection

### 3. Gap Analyzer
- [ ] Create `governance/gap_analyzer.py`
- [ ] Implement failed query collection
- [ ] Implement query clustering
- [ ] Implement gap identification
- [ ] Generate suggested titles

### 4. Coverage Analyzer
- [ ] Implement topic extraction
- [ ] Calculate coverage ratios
- [ ] Build coverage matrix
- [ ] Identify underserved topics

### 5. API Endpoints
- [ ] Create `api/governance.py`
- [ ] Implement `/governance/obsolete`
- [ ] Implement `/governance/gaps`
- [ ] Implement `/governance/coverage`
- [ ] Implement `/governance/low-quality`

### 6. Reports
- [ ] Create `governance/reports.py`
- [ ] Generate summary report
- [ ] Export to CSV/JSON
- [ ] Add email/Slack notification option

### 7. CLI Commands
- [ ] Add `governance report` command
- [ ] Add `governance obsolete` command
- [ ] Add `governance gaps` command
- [ ] Add `governance export` command

## Post-Implementation
- [ ] Run tests from TEST.md
- [ ] Update PROGRESS.md status to ✅ Done
- [ ] Commit: "feat(phase-12): governance reports"
