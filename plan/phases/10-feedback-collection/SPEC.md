# Phase 10: Feedback Collection

## Overview

Collect explicit user feedback (thumbs up/down) from Slack responses and store for learning.

## Dependencies

- **Requires**: Phase 08 (Slack Bot)
- **Blocks**: Phase 11 (Quality Scoring)
- **Parallel**: Phase 10.5 (Behavioral Signals)

## Deliverables

```
src/knowledge_base/
├── feedback/
│   ├── __init__.py
│   ├── collector.py          # Store feedback
│   └── models.py             # Feedback data models
├── slack/
│   └── interactions.py       # Button click handlers
```

## Technical Specification

### Feedback Model

```python
class Feedback(Base):
    __tablename__ = "feedback"

    id: int
    response_id: str              # Unique response tracking ID
    user_id: str                  # Slack user ID
    query: str                    # Original question
    documents_shown: str          # JSON: list of page_ids in answer
    feedback_type: str            # "thumbs_up", "thumbs_down", "partial"
    feedback_value: float         # Normalized: +1.0, -1.0, 0.0
    suggestion_text: str | None   # User's improvement suggestion
    created_at: datetime
```

### Feedback Buttons

```python
def create_feedback_buttons(response_id: str) -> list[dict]:
    return [
        {
            "type": "actions",
            "block_id": f"feedback_{response_id}",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "👍 Helpful"},
                    "action_id": "feedback_positive",
                    "value": response_id
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "👎 Not helpful"},
                    "action_id": "feedback_negative",
                    "value": response_id
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "🔄 Partially"},
                    "action_id": "feedback_partial",
                    "value": response_id
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "💡 Suggest"},
                    "action_id": "feedback_suggest",
                    "value": response_id
                }
            ]
        }
    ]
```

### Button Handlers

```python
@app.action("feedback_positive")
async def handle_positive(ack, body, client):
    await ack()
    response_id = body["actions"][0]["value"]
    user_id = body["user"]["id"]

    await feedback_collector.record(
        response_id=response_id,
        user_id=user_id,
        feedback_type="thumbs_up",
        feedback_value=1.0
    )

    # Update message to show feedback received
    await client.chat_update(
        channel=body["channel"]["id"],
        ts=body["message"]["ts"],
        blocks=update_with_thanks(body["message"]["blocks"])
    )

@app.action("feedback_negative")
async def handle_negative(ack, body, client):
    await ack()
    response_id = body["actions"][0]["value"]
    user_id = body["user"]["id"]

    await feedback_collector.record(
        response_id=response_id,
        user_id=user_id,
        feedback_type="thumbs_down",
        feedback_value=-1.0
    )

    # Open modal for more details
    await client.views_open(
        trigger_id=body["trigger_id"],
        view=create_feedback_modal(response_id)
    )

@app.action("feedback_suggest")
async def handle_suggest(ack, body, client):
    await ack()
    response_id = body["actions"][0]["value"]

    await client.views_open(
        trigger_id=body["trigger_id"],
        view=create_suggestion_modal(response_id)
    )
```

### Suggestion Modal

```python
def create_suggestion_modal(response_id: str) -> dict:
    return {
        "type": "modal",
        "callback_id": f"suggestion_submit_{response_id}",
        "title": {"type": "plain_text", "text": "Suggest Improvement"},
        "submit": {"type": "plain_text", "text": "Submit"},
        "blocks": [
            {
                "type": "input",
                "block_id": "suggestion_input",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "suggestion_text",
                    "multiline": True,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "What could be improved?"
                    }
                },
                "label": {"type": "plain_text", "text": "Your suggestion"}
            },
            {
                "type": "input",
                "block_id": "issue_type",
                "element": {
                    "type": "static_select",
                    "action_id": "issue_select",
                    "options": [
                        {"text": {"type": "plain_text", "text": "Answer was incorrect"}, "value": "incorrect"},
                        {"text": {"type": "plain_text", "text": "Answer was incomplete"}, "value": "incomplete"},
                        {"text": {"type": "plain_text", "text": "Sources were outdated"}, "value": "outdated"},
                        {"text": {"type": "plain_text", "text": "Didn't answer my question"}, "value": "irrelevant"},
                        {"text": {"type": "plain_text", "text": "Other"}, "value": "other"}
                    ]
                },
                "label": {"type": "plain_text", "text": "Issue type"}
            }
        ]
    }
```

### Feedback Collector

```python
class FeedbackCollector:
    async def record(
        self,
        response_id: str,
        user_id: str,
        feedback_type: str,
        feedback_value: float,
        suggestion_text: str | None = None
    ):
        # Get response context from cache/DB
        response_context = await self.get_response_context(response_id)

        feedback = Feedback(
            response_id=response_id,
            user_id=user_id,
            query=response_context.query,
            documents_shown=json.dumps(response_context.document_ids),
            feedback_type=feedback_type,
            feedback_value=feedback_value,
            suggestion_text=suggestion_text
        )

        await self.db.add(feedback)
        await self.db.commit()
```

## Definition of Done

- [ ] Feedback buttons appear on all responses
- [ ] Clicking buttons stores feedback
- [ ] Negative feedback opens detail modal
- [ ] Suggestions stored with context
- [ ] Feedback linked to documents shown
