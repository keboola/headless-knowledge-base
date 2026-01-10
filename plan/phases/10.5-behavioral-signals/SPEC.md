# Phase 10.5: Behavioral Signals

## Overview

Collect implicit feedback from Slack interactions: follow-ups, reactions, gratitude detection, thread patterns.

## Dependencies

- **Requires**: Phase 10 (Feedback Collection)
- **Blocks**: None (enhancement)
- **Enhances**: Quality Scoring

## Deliverables

```
src/knowledge_base/
├── feedback/
│   ├── behavior_tracker.py   # Track implicit signals
│   └── signal_analyzer.py    # Detect patterns in text
```

## Technical Specification

### Signal Types

| Signal | Detection | Score Impact |
|--------|-----------|--------------|
| Follow-up question | User sends another message in thread | -0.3 |
| Thread abandonment | No activity 5 min after response | +0.1 |
| Emoji reaction (positive) | 👍, ✅, 🎉 on bot message | +0.5 |
| Emoji reaction (negative) | 👎, ❌ on bot message | -0.5 |
| Question rephrasing | Similar query within 10 min | -0.4 |
| Gratitude expression | "thanks", "helpful", "perfect" | +0.2 |
| Frustration expression | "not helpful", "wrong", "doesn't work" | -0.5 |

### Behavior Tracker

```python
class SlackBehaviorTracker:
    def __init__(self, db: Database, analyzer: SignalAnalyzer):
        self.db = db
        self.analyzer = analyzer
        self.pending_timeouts = {}

    async def on_bot_response(self, response_id: str, thread_ts: str):
        """Start tracking after bot responds."""
        # Schedule timeout check
        self.pending_timeouts[thread_ts] = asyncio.create_task(
            self.check_timeout(response_id, thread_ts, delay=300)
        )

    async def on_thread_message(self, event: dict):
        """Handle user message in thread."""
        thread_ts = event.get("thread_ts")
        text = event["text"]
        user_id = event["user"]

        # Cancel timeout (user engaged)
        if thread_ts in self.pending_timeouts:
            self.pending_timeouts[thread_ts].cancel()
            del self.pending_timeouts[thread_ts]

        # Get response context
        response = await self.get_response_for_thread(thread_ts)
        if not response:
            return

        # Analyze message
        if self.analyzer.is_follow_up_question(text):
            await self.record_signal(response.id, "follow_up", -0.3, user_id)
        elif self.analyzer.is_gratitude(text):
            await self.record_signal(response.id, "thanks", +0.2, user_id)
        elif self.analyzer.is_frustration(text):
            await self.record_signal(response.id, "frustration", -0.5, user_id)

    async def on_reaction_added(self, event: dict):
        """Handle emoji reaction on bot message."""
        reaction = event["reaction"]
        item_ts = event["item"]["ts"]
        user_id = event["user"]

        response = await self.get_response_for_message(item_ts)
        if not response:
            return

        if reaction in ["thumbsup", "+1", "white_check_mark", "tada", "heart"]:
            await self.record_signal(response.id, "positive_reaction", +0.5, user_id)
        elif reaction in ["thumbsdown", "-1", "x", "no_entry"]:
            await self.record_signal(response.id, "negative_reaction", -0.5, user_id)

    async def check_timeout(self, response_id: str, thread_ts: str, delay: int):
        """Check if thread was abandoned (positive signal)."""
        await asyncio.sleep(delay)

        # If we get here, no follow-up was sent
        if thread_ts in self.pending_timeouts:
            await self.record_signal(response_id, "satisfied_silence", +0.1)
            del self.pending_timeouts[thread_ts]
```

### Signal Analyzer

```python
class SignalAnalyzer:
    GRATITUDE_PATTERNS = [
        r"\bthanks?\b", r"\bthank you\b", r"\bhelpful\b",
        r"\bperfect\b", r"\bgreat\b", r"\bawesome\b",
        r"\bthat('s| is) (exactly )?what i needed\b"
    ]

    FRUSTRATION_PATTERNS = [
        r"\bnot helpful\b", r"\bwrong\b", r"\bdoesn't (work|help)\b",
        r"\bthat's not\b", r"\bstill don't\b", r"\bconfused\b"
    ]

    QUESTION_PATTERNS = [
        r"\?$", r"^(what|how|why|when|where|who|can|could|would)\b"
    ]

    def is_gratitude(self, text: str) -> bool:
        text = text.lower()
        return any(re.search(p, text) for p in self.GRATITUDE_PATTERNS)

    def is_frustration(self, text: str) -> bool:
        text = text.lower()
        return any(re.search(p, text) for p in self.FRUSTRATION_PATTERNS)

    def is_follow_up_question(self, text: str) -> bool:
        text = text.lower().strip()
        return any(re.search(p, text) for p in self.QUESTION_PATTERNS)

    def is_similar_query(self, query1: str, query2: str, threshold: float = 0.7) -> bool:
        """Check if queries are similar (rephrasing)."""
        # Simple: word overlap
        words1 = set(query1.lower().split())
        words2 = set(query2.lower().split())
        overlap = len(words1 & words2) / max(len(words1 | words2), 1)
        return overlap > threshold
```

### Behavioral Signal Model

```python
class BehavioralSignal(Base):
    __tablename__ = "behavioral_signals"

    id: int
    response_id: str              # Link to response
    user_id: str                  # Who generated signal
    signal_type: str              # follow_up, thanks, etc.
    signal_value: float           # Score impact
    raw_text: str | None          # Original text (for analysis)
    created_at: datetime
```

### Slack Event Handlers

```python
@app.event("message")
async def handle_message(event, client):
    # Only handle thread replies
    if "thread_ts" not in event:
        return
    if event.get("bot_id"):  # Ignore bot messages
        return

    await behavior_tracker.on_thread_message(event)

@app.event("reaction_added")
async def handle_reaction(event, client):
    await behavior_tracker.on_reaction_added(event)
```

## Definition of Done

- [ ] Thread messages analyzed for signals
- [ ] Emoji reactions tracked
- [ ] Gratitude/frustration detected
- [ ] Timeout tracking works
- [ ] Signals stored in database
