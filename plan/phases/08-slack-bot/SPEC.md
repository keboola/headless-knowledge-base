# Phase 08: Slack Bot

## Overview

Implement Slack bot with /ask command, @mention support, and threaded responses.

## Dependencies

- **Requires**: Phase 07 (RAG Answers)
- **Blocks**: Phase 09 (Permissions), Phase 10 (Feedback)

## Deliverables

```
src/knowledge_base/
├── slack/
│   ├── __init__.py
│   ├── app.py                # Bolt app setup
│   ├── commands.py           # /ask command handler
│   ├── events.py             # Mention, DM handlers
│   ├── messages.py           # Message formatting
│   └── auth.py               # Slack OAuth setup
```

## Technical Specification

### Slack App Setup

```python
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler

app = AsyncApp(
    token=os.environ["SLACK_BOT_TOKEN"],
    signing_secret=os.environ["SLACK_SIGNING_SECRET"]
)

handler = AsyncSlackRequestHandler(app)
```

### /ask Command Handler

```python
@app.command("/ask")
async def handle_ask(ack, command, client):
    await ack()  # Acknowledge immediately

    query = command["text"]
    user_id = command["user_id"]
    channel_id = command["channel_id"]

    # Show typing indicator
    await client.chat_postMessage(
        channel=channel_id,
        text="Searching knowledge base..."
    )

    # Get RAG answer
    response = await rag_chain.answer(query)

    # Format and send response
    message = format_response(response)
    await client.chat_postMessage(
        channel=channel_id,
        blocks=message.blocks,
        text=message.fallback_text
    )
```

### @Mention Handler

```python
@app.event("app_mention")
async def handle_mention(event, client):
    # Extract query (remove bot mention)
    query = re.sub(r"<@\w+>", "", event["text"]).strip()

    if not query:
        await client.chat_postMessage(
            channel=event["channel"],
            thread_ts=event["ts"],
            text="Please include a question after mentioning me!"
        )
        return

    response = await rag_chain.answer(query)
    message = format_response(response)

    await client.chat_postMessage(
        channel=event["channel"],
        thread_ts=event["ts"],  # Reply in thread
        blocks=message.blocks
    )
```

### Message Formatting

```python
def format_response(response: RAGResponse) -> SlackMessage:
    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": response.answer}
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Sources:*\n" + format_sources(response.sources)
            }
        },
        {
            "type": "actions",
            "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": "👍 Helpful"}, "action_id": "feedback_positive"},
                {"type": "button", "text": {"type": "plain_text", "text": "👎 Not helpful"}, "action_id": "feedback_negative"}
            ]
        }
    ]

    return SlackMessage(blocks=blocks, fallback_text=response.answer)

def format_sources(sources: list[SearchResult]) -> str:
    lines = []
    for s in sources[:3]:
        age = get_age_string(s.metadata.get("updated_at"))
        lines.append(f"• <{s.url}|{s.page_title}> ({age})")
    return "\n".join(lines)
```

### DM Support

```python
@app.event("message")
async def handle_dm(event, client):
    # Only handle DMs (not channel messages)
    if event.get("channel_type") != "im":
        return

    query = event["text"]
    response = await rag_chain.answer(query)
    message = format_response(response)

    await client.chat_postMessage(
        channel=event["channel"],
        blocks=message.blocks
    )
```

### FastAPI Integration

```python
# main.py
from knowledge_base.slack.app import handler

@app.post("/slack/events")
async def slack_events(request: Request):
    return await handler.handle(request)

@app.post("/slack/commands")
async def slack_commands(request: Request):
    return await handler.handle(request)
```

## Slack App Manifest

```yaml
display_information:
  name: Knowledge Base Bot

features:
  bot_user:
    display_name: knowledge-bot
  slash_commands:
    - command: /ask
      description: Ask the knowledge base a question
      usage_hint: "[your question]"

oauth_config:
  scopes:
    bot:
      - chat:write
      - commands
      - app_mentions:read
      - im:read
      - im:write

settings:
  event_subscriptions:
    bot_events:
      - app_mention
      - message.im
```

## Definition of Done

- [ ] /ask command works
- [ ] @mention triggers response
- [ ] DM conversations work
- [ ] Responses in threads (for channels)
- [ ] Sources linked correctly
- [ ] Feedback buttons present
