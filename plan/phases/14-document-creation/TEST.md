# Phase 14: Document Creation - Test Plan

## Quick Verification

```bash
# Test /create-doc command in Slack
# 1. Type /create-doc in any channel
# 2. Fill modal: title, description, area=general, type=information
# 3. Should be published immediately
# 4. Search for it - should be found
```

## Functional Tests

### 1. Create Guideline (Auto-Publish)
```
1. /create-doc
2. Fill:
   - Title: "How to request laptop"
   - Description: "Steps to request a new laptop"
   - Area: general
   - Type: guideline
   - Classification: internal
3. Submit
4. Expected: "Document published!" message
5. Search "request laptop" → should find doc
```

### 2. Create Policy (Approval Required)
```
1. /create-doc
2. Fill:
   - Title: "Remote Work Policy"
   - Description: "Rules for working remotely"
   - Area: people
   - Type: policy
   - Classification: internal
3. Submit
4. Expected: "Sent for approval" message
5. Check approver DM → should have approval request
6. Search "remote work" → should NOT find (not published yet)
7. Approver clicks Approve
8. Search "remote work" → should find doc now
```

### 3. Thread-to-Doc
```
1. Create a Slack thread with Q&A about a topic
2. Use message shortcut "Save as Doc" on the thread
3. Modal opens with AI-generated title and content
4. Review and submit
5. Expected: Doc created from thread summary
```

### 4. Approval Rejection
```
1. Create a policy doc
2. Approver clicks Reject
3. Expected: Creator notified of rejection
4. Doc status = "draft" (can edit and resubmit)
```

## Unit Tests

```python
# tests/test_document_creation.py
import pytest
from knowledge_base.documents.creator import create_document
from knowledge_base.documents.approval import APPROVAL_REQUIRED

def test_approval_rules():
    assert APPROVAL_REQUIRED["policy"] == True
    assert APPROVAL_REQUIRED["procedure"] == True
    assert APPROVAL_REQUIRED["guideline"] == False
    assert APPROVAL_REQUIRED["information"] == False

@pytest.mark.asyncio
async def test_create_guideline_auto_publishes():
    doc = await create_document(
        title="Test Guide",
        content="Test content",
        area="general",
        doc_type="guideline",
        classification="internal",
        created_by="U123"
    )
    assert doc.status == "published"

@pytest.mark.asyncio
async def test_create_policy_needs_approval():
    doc = await create_document(
        title="Test Policy",
        content="Test content",
        area="people",
        doc_type="policy",
        classification="internal",
        created_by="U123"
    )
    assert doc.status == "draft"

@pytest.mark.asyncio
async def test_ai_draft_from_description():
    drafter = AIDocDrafter()
    content = await drafter.draft_from_description(
        "How to request time off using Workday",
        "guideline"
    )
    assert len(content) > 100
    assert "workday" in content.lower() or "time off" in content.lower()

@pytest.mark.asyncio
async def test_ai_draft_from_thread():
    messages = [
        {"text": "How do I get VPN access?"},
        {"text": "You need to submit a ticket to IT"},
        {"text": "The form is at helpdesk.company.com"},
    ]
    drafter = AIDocDrafter()
    title, content = await drafter.draft_from_thread(messages, "information")
    assert "VPN" in title or "VPN" in content
```

## Integration Test

```python
@pytest.mark.asyncio
async def test_full_creation_flow():
    # 1. Create policy
    doc = await create_document(
        title="Expense Policy",
        content="All expenses over $100 need approval",
        area="finance",
        doc_type="policy",
        classification="internal",
        created_by="U_CREATOR"
    )
    assert doc.status == "draft"

    # 2. Verify not searchable
    results = await search("expense policy")
    assert not any(r.id == doc.id for r in results)

    # 3. Approve
    await approve_document(doc.id, approver="U_APPROVER")

    # 4. Verify now searchable
    results = await search("expense policy")
    assert any(r.id == doc.id for r in results)
```

## Success Criteria

- [ ] /create-doc modal works
- [ ] AI generates reasonable drafts
- [ ] Guidelines publish immediately
- [ ] Policies require approval
- [ ] Thread-to-doc works
- [ ] Approved docs are searchable
- [ ] Rejected docs notify creator
