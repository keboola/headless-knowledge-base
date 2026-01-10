# Phase 08: Slack Bot - Test Plan

## Quick Verification

```
In Slack:
1. Type: /ask How do I request PTO?
2. Bot should respond with answer and sources
```

## Functional Tests

### 1. /ask Command
```
In Slack channel:
> /ask What is the vacation policy?

Expected:
- Bot responds within 10 seconds
- Answer includes relevant information
- Sources listed with links
- Feedback buttons present
```

### 2. @Mention
```
In Slack channel:
> @knowledge-bot How do I deploy to production?

Expected:
- Bot responds in thread
- Answer is relevant
- Sources included
```

### 3. Direct Message
```
In DM with bot:
> What are the company holidays?

Expected:
- Bot responds directly (not in thread)
- Full answer with sources
```

### 4. Empty Query
```
> /ask
> @knowledge-bot

Expected:
- Bot asks for a question
- Helpful error message
```

### 5. Source Links
```
> /ask onboarding process

Expected:
- Source links are clickable
- Links go to correct Confluence pages
- Age indicator shown (e.g., "2 months ago")
```

### 6. Feedback Buttons
```
> /ask How do I submit expenses?

Expected:
- 👍 and 👎 buttons visible
- Clicking them triggers action (Phase 10)
```

## API Tests

### 1. Events Endpoint
```bash
# Simulate Slack verification challenge
curl -X POST http://localhost:8000/slack/events \
  -H "Content-Type: application/json" \
  -d '{"type": "url_verification", "challenge": "test123"}'
# Expected: {"challenge": "test123"}
```

### 2. Command Endpoint
```bash
# Note: Real Slack commands have signature verification
# This tests the endpoint exists
curl -X POST http://localhost:8000/slack/commands \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "command=/ask&text=test"
# Expected: 200 or 401 (signature required)
```

## Unit Tests

```python
# tests/test_slack.py
import pytest
from knowledge_base.slack.messages import format_response, format_sources

def test_format_response():
    response = MockRAGResponse(
        answer="Here is your answer",
        sources=[MockSource("Page 1", "http://example.com")]
    )
    message = format_response(response)

    assert len(message.blocks) > 0
    assert "answer" in str(message.blocks).lower()

def test_format_sources():
    sources = [
        MockSource("PTO Policy", "http://confluence/pto", "2024-01-01"),
        MockSource("Benefits", "http://confluence/benefits", "2023-06-01"),
    ]
    formatted = format_sources(sources)

    assert "PTO Policy" in formatted
    assert "http://confluence/pto" in formatted

def test_extract_query_from_mention():
    from knowledge_base.slack.events import extract_query

    text = "<@U123ABC> How do I request PTO?"
    query = extract_query(text)

    assert query == "How do I request PTO?"
```

## Integration Test

```python
# tests/test_slack_integration.py
import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_ask_command_flow():
    with patch("knowledge_base.rag.chain.RAGChain.answer") as mock_answer:
        mock_answer.return_value = MockRAGResponse(
            answer="Test answer",
            sources=[]
        )

        from knowledge_base.slack.commands import handle_ask

        ack = AsyncMock()
        client = AsyncMock()
        command = {
            "text": "test query",
            "user_id": "U123",
            "channel_id": "C123"
        }

        await handle_ask(ack, command, client)

        ack.assert_called_once()
        client.chat_postMessage.assert_called()
```

## Success Criteria

- [ ] /ask command responds correctly
- [ ] @mention works in channels
- [ ] DM conversations work
- [ ] Responses appear in threads
- [ ] Source links work
- [ ] Feedback buttons visible
- [ ] Handles errors gracefully
