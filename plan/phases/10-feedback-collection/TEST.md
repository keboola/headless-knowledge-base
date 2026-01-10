# Phase 10: Feedback Collection - Test Plan

## Quick Verification

```
In Slack:
1. /ask How do I request PTO?
2. Click 👍 button
3. Check database for feedback record
```

## Functional Tests

### 1. Positive Feedback
```
> /ask vacation policy

(Bot responds with answer)

Click: 👍 Helpful

Expected:
- Button click acknowledged
- Message updated to show thanks
- Database record created with feedback_value = 1.0
```

### 2. Negative Feedback
```
> /ask some question

Click: 👎 Not helpful

Expected:
- Modal opens asking for details
- User selects issue type
- Submit stores feedback_value = -1.0
- Issue type stored
```

### 3. Partial Feedback
```
> /ask complex question

Click: 🔄 Partially

Expected:
- Feedback stored with feedback_value = 0.0
- Optionally opens modal for details
```

### 4. Suggestion Flow
```
> /ask some question

Click: 💡 Suggest

Expected:
- Modal opens with text input
- User enters suggestion
- Submit stores suggestion_text
- Modal closes with confirmation
```

### 5. Database Records
```bash
# Check feedback records
sqlite3 knowledge_base.db "
SELECT
    feedback_type,
    feedback_value,
    SUBSTR(query, 1, 30) as query,
    json_array_length(documents_shown) as doc_count
FROM feedback
ORDER BY created_at DESC
LIMIT 10;
"
```

### 6. Button Disabling
```
After clicking any feedback button:
- Buttons should be disabled/hidden
- Cannot submit multiple feedbacks
```

## Unit Tests

```python
# tests/test_feedback.py
import pytest
from knowledge_base.feedback.collector import FeedbackCollector
from knowledge_base.feedback.models import Feedback

@pytest.mark.asyncio
async def test_record_positive_feedback():
    collector = FeedbackCollector(db_session)

    await collector.record(
        response_id="resp_123",
        user_id="U123",
        feedback_type="thumbs_up",
        feedback_value=1.0
    )

    feedback = await db_session.query(Feedback).filter_by(
        response_id="resp_123"
    ).first()

    assert feedback is not None
    assert feedback.feedback_value == 1.0

@pytest.mark.asyncio
async def test_record_with_suggestion():
    collector = FeedbackCollector(db_session)

    await collector.record(
        response_id="resp_456",
        user_id="U123",
        feedback_type="suggestion",
        feedback_value=0.0,
        suggestion_text="Should mention the deadline"
    )

    feedback = await db_session.query(Feedback).filter_by(
        response_id="resp_456"
    ).first()

    assert feedback.suggestion_text == "Should mention the deadline"

def test_feedback_buttons_structure():
    from knowledge_base.slack.messages import create_feedback_buttons

    buttons = create_feedback_buttons("resp_789")

    assert len(buttons) == 1  # One actions block
    assert len(buttons[0]["elements"]) == 4  # 4 buttons
    assert buttons[0]["elements"][0]["value"] == "resp_789"
```

## Integration Test

```python
@pytest.mark.asyncio
async def test_feedback_flow():
    # Simulate Slack interaction
    from knowledge_base.slack.interactions import handle_positive

    body = {
        "actions": [{"value": "resp_test"}],
        "user": {"id": "U123"},
        "channel": {"id": "C123"},
        "message": {"ts": "123.456", "blocks": []}
    }

    ack = AsyncMock()
    client = AsyncMock()

    # Store response context first
    await response_cache.set("resp_test", {
        "query": "test query",
        "document_ids": ["doc1", "doc2"]
    })

    await handle_positive(ack, body, client)

    ack.assert_called_once()

    # Check feedback stored
    feedback = await get_feedback("resp_test")
    assert feedback is not None
    assert feedback.documents_shown == '["doc1", "doc2"]'
```

## Success Criteria

- [ ] All 4 feedback buttons work
- [ ] Feedback stored in database
- [ ] Documents linked to feedback
- [ ] Modals open and submit correctly
- [ ] Buttons disabled after feedback
- [ ] Multiple users can give feedback
