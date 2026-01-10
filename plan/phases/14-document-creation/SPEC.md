# Phase 14: Document Creation

## Overview

Enable document creation directly in the knowledge base via Slack. AI drafts content from user description or thread summary. Approval workflow based on doc_type and area.

## Dependencies

- **Requires**: Phase 07 (RAG), Phase 08 (Slack Bot)
- **Blocks**: None

## Deliverables

```
src/knowledge_base/
├── documents/
│   ├── __init__.py
│   ├── models.py           # Document, AreaApprovers models
│   ├── creator.py          # Document creation logic
│   ├── approval.py         # Approval workflow
│   └── ai_drafter.py       # AI content generation
├── slack/
│   └── doc_commands.py     # /create-doc, /save-as-doc handlers
```

## Technical Specification

### Document Model

```python
class Document(Base):
    __tablename__ = "documents"

    id: str                     # UUID
    title: str
    content: str                # Markdown content

    # Governance
    area: str                   # "people", "finance", "engineering", etc.
    doc_type: str               # "policy", "procedure", "guideline", "information"
    classification: str         # "public", "internal", "confidential"
    owner: str                  # Contact person (default: creator)

    # Lifecycle
    status: str                 # "draft", "in_review", "approved", "published"
    created_by: str             # Slack user ID
    created_at: datetime
    approved_by: str | None
    approved_at: datetime | None

    # Source tracking
    source_type: str            # "manual", "thread_summary", "ai_draft"
    source_thread_ts: str | None  # If created from thread
```

### Area Approvers

```python
class AreaApprovers(Base):
    __tablename__ = "area_approvers"

    area: str                   # "people", "finance", etc.
    approvers: str              # JSON list of Slack user IDs

# Example data:
# area="people", approvers=["U123", "U456"]
# area="finance", approvers=["U789"]
```

### Approval Rules

```python
APPROVAL_REQUIRED = {
    "policy": True,
    "procedure": True,
    "guideline": False,
    "information": False,
}

async def get_approvers(area: str) -> list[str]:
    """Get approver Slack IDs for an area."""
    record = await db.get(AreaApprovers, area=area)
    return json.loads(record.approvers) if record else []
```

### Document Creation Flow

```python
async def create_document(
    title: str,
    content: str,
    area: str,
    doc_type: str,
    classification: str,
    created_by: str,
    source_type: str = "manual",
    source_thread_ts: str | None = None
) -> Document:
    """Create a new document with appropriate workflow."""

    doc = Document(
        id=uuid4(),
        title=title,
        content=content,
        area=area,
        doc_type=doc_type,
        classification=classification,
        owner=created_by,
        created_by=created_by,
        source_type=source_type,
        source_thread_ts=source_thread_ts,
        status="draft" if APPROVAL_REQUIRED[doc_type] else "published"
    )

    await db.add(doc)

    if APPROVAL_REQUIRED[doc_type]:
        await request_approval(doc)
    else:
        await index_document(doc)  # Make searchable immediately

    return doc
```

### AI Content Drafting

```python
class AIDocDrafter:
    """Generate document drafts using AI."""

    async def draft_from_description(
        self,
        description: str,
        doc_type: str
    ) -> str:
        """Generate doc from user's brief description."""
        prompt = f"""Create a {doc_type} document based on this description:

{description}

Format as clear, concise markdown. Include sections as appropriate."""

        return await self.llm.generate(prompt)

    async def draft_from_thread(
        self,
        messages: list[dict],
        doc_type: str
    ) -> tuple[str, str]:
        """Generate doc title and content from Slack thread."""
        thread_text = "\n".join([m["text"] for m in messages])

        prompt = f"""Summarize this Slack discussion into a {doc_type} document.

Discussion:
{thread_text}

Return JSON: {{"title": "...", "content": "..."}}
Content should be clear markdown capturing the key information."""

        result = await self.llm.generate(prompt)
        parsed = json.loads(result)
        return parsed["title"], parsed["content"]
```

### Slack Commands

```python
@app.command("/create-doc")
async def handle_create_doc(ack, body, client):
    """Open document creation modal."""
    await ack()

    await client.views_open(
        trigger_id=body["trigger_id"],
        view=create_doc_modal()
    )

def create_doc_modal() -> dict:
    return {
        "type": "modal",
        "callback_id": "create_doc_submit",
        "title": {"type": "plain_text", "text": "Create Document"},
        "submit": {"type": "plain_text", "text": "Create"},
        "blocks": [
            {
                "type": "input",
                "block_id": "title",
                "element": {"type": "plain_text_input", "action_id": "title_input"},
                "label": {"type": "plain_text", "text": "Title"}
            },
            {
                "type": "input",
                "block_id": "description",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "desc_input",
                    "multiline": True,
                    "placeholder": {"type": "plain_text", "text": "Describe what this doc should cover..."}
                },
                "label": {"type": "plain_text", "text": "Description (AI will draft content)"}
            },
            {
                "type": "input",
                "block_id": "area",
                "element": {
                    "type": "static_select",
                    "action_id": "area_select",
                    "options": [
                        {"text": {"type": "plain_text", "text": "People"}, "value": "people"},
                        {"text": {"type": "plain_text", "text": "Finance"}, "value": "finance"},
                        {"text": {"type": "plain_text", "text": "Engineering"}, "value": "engineering"},
                        {"text": {"type": "plain_text", "text": "General"}, "value": "general"},
                    ]
                },
                "label": {"type": "plain_text", "text": "Area"}
            },
            {
                "type": "input",
                "block_id": "doc_type",
                "element": {
                    "type": "static_select",
                    "action_id": "type_select",
                    "options": [
                        {"text": {"type": "plain_text", "text": "Policy"}, "value": "policy"},
                        {"text": {"type": "plain_text", "text": "Procedure"}, "value": "procedure"},
                        {"text": {"type": "plain_text", "text": "Guideline"}, "value": "guideline"},
                        {"text": {"type": "plain_text", "text": "Information"}, "value": "information"},
                    ]
                },
                "label": {"type": "plain_text", "text": "Document Type"}
            },
            {
                "type": "input",
                "block_id": "classification",
                "element": {
                    "type": "static_select",
                    "action_id": "class_select",
                    "options": [
                        {"text": {"type": "plain_text", "text": "Public"}, "value": "public"},
                        {"text": {"type": "plain_text", "text": "Internal"}, "value": "internal"},
                        {"text": {"type": "plain_text", "text": "Confidential"}, "value": "confidential"},
                    ]
                },
                "label": {"type": "plain_text", "text": "Classification"}
            },
        ]
    }
```

### Save Thread as Document

```python
@app.shortcut("save_as_doc")
async def handle_save_as_doc(ack, shortcut, client):
    """Create doc from thread via message shortcut."""
    await ack()

    # Get thread messages
    thread_ts = shortcut["message"]["thread_ts"] or shortcut["message"]["ts"]
    result = await client.conversations_replies(
        channel=shortcut["channel"]["id"],
        ts=thread_ts
    )
    messages = result["messages"]

    # Draft with AI
    drafter = AIDocDrafter()
    title, content = await drafter.draft_from_thread(messages, "information")

    # Show modal with pre-filled draft
    await client.views_open(
        trigger_id=shortcut["trigger_id"],
        view=create_doc_modal_prefilled(title, content, thread_ts)
    )
```

### Approval Workflow

```python
async def request_approval(doc: Document):
    """Send approval request to area approvers."""
    approvers = await get_approvers(doc.area)

    doc.status = "in_review"
    await db.commit()

    for approver_id in approvers:
        await slack_client.chat_postMessage(
            channel=approver_id,
            text=f"New {doc.doc_type} needs approval: {doc.title}",
            blocks=[
                {"type": "section", "text": {"type": "mrkdwn", "text": f"*{doc.title}*\n\n{doc.content[:500]}..."}},
                {
                    "type": "actions",
                    "elements": [
                        {"type": "button", "text": {"type": "plain_text", "text": "✅ Approve"}, "action_id": "approve_doc", "value": doc.id},
                        {"type": "button", "text": {"type": "plain_text", "text": "❌ Reject"}, "action_id": "reject_doc", "value": doc.id},
                        {"type": "button", "text": {"type": "plain_text", "text": "✏️ Edit"}, "action_id": "edit_doc", "value": doc.id},
                    ]
                }
            ]
        )

@app.action("approve_doc")
async def handle_approve(ack, body, client):
    await ack()
    doc_id = body["actions"][0]["value"]
    approver = body["user"]["id"]

    doc = await db.get(Document, id=doc_id)
    doc.status = "published"
    doc.approved_by = approver
    doc.approved_at = datetime.utcnow()
    await db.commit()

    # Index for search
    await index_document(doc)

    # Notify creator
    await client.chat_postMessage(
        channel=doc.created_by,
        text=f"✅ Your document '{doc.title}' has been approved and published!"
    )
```

## Definition of Done

- [ ] /create-doc command works
- [ ] AI drafts content from description
- [ ] Thread-to-doc conversion works
- [ ] Approval workflow for policy/procedure
- [ ] Direct publish for guideline/information
- [ ] Documents indexed and searchable after publish
- [ ] Area approvers configurable
