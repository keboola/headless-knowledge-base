# Phase 10.5: Behavioral Signals - Test Plan

## Quick Verification

```
In Slack:
1. /ask How do I request PTO?
2. Reply in thread: "Thanks, that's helpful!"
3. Check database for behavioral signal
```

## Functional Tests

### 1. Gratitude Detection
```
> /ask vacation policy
Bot: (answers)
User in thread: "Thanks, that's exactly what I needed!"

Check:
sqlite3 knowledge_base.db "
SELECT signal_type, signal_value FROM behavioral_signals
ORDER BY created_at DESC LIMIT 1;
"
Expected: thanks, 0.2
```

### 2. Frustration Detection
```
> /ask how to deploy
Bot: (answers)
User in thread: "That's not helpful, it doesn't work"

Check database:
Expected: frustration, -0.5
```

### 3. Follow-up Question
```
> /ask benefits
Bot: (answers)
User in thread: "What about dental coverage?"

Check database:
Expected: follow_up, -0.3
```

### 4. Positive Reaction
```
> /ask expense policy
Bot: (answers)
User: Adds 👍 reaction to bot message

Check database:
Expected: positive_reaction, 0.5
```

### 5. Negative Reaction
```
> /ask something
Bot: (answers)
User: Adds 👎 reaction to bot message

Check database:
Expected: negative_reaction, -0.5
```

### 6. Satisfied Silence
```
> /ask quick question
Bot: (answers)
User: (does nothing for 5+ minutes)

Check database (after timeout):
Expected: satisfied_silence, 0.1
```

## Unit Tests

```python
# tests/test_behavioral_signals.py
import pytest
from knowledge_base.feedback.signal_analyzer import SignalAnalyzer

def test_detect_gratitude():
    analyzer = SignalAnalyzer()

    assert analyzer.is_gratitude("Thanks!") is True
    assert analyzer.is_gratitude("That's helpful") is True
    assert analyzer.is_gratitude("Perfect, exactly what I needed") is True
    assert analyzer.is_gratitude("Where is the office?") is False

def test_detect_frustration():
    analyzer = SignalAnalyzer()

    assert analyzer.is_frustration("That's not helpful") is True
    assert analyzer.is_frustration("This is wrong") is True
    assert analyzer.is_frustration("It doesn't work") is True
    assert analyzer.is_frustration("Thanks!") is False

def test_detect_follow_up():
    analyzer = SignalAnalyzer()

    assert analyzer.is_follow_up_question("What about dental?") is True
    assert analyzer.is_follow_up_question("How do I apply?") is True
    assert analyzer.is_follow_up_question("Thanks!") is False
    assert analyzer.is_follow_up_question("OK") is False

@pytest.mark.asyncio
async def test_reaction_tracking():
    tracker = SlackBehaviorTracker(db, analyzer)

    # Setup response mapping
    await tracker.set_response_mapping("msg_123", "resp_456")

    event = {
        "reaction": "thumbsup",
        "item": {"ts": "msg_123"},
        "user": "U123"
    }

    await tracker.on_reaction_added(event)

    signal = await db.query(BehavioralSignal).filter_by(
        response_id="resp_456"
    ).first()

    assert signal is not None
    assert signal.signal_type == "positive_reaction"
    assert signal.signal_value == 0.5

@pytest.mark.asyncio
async def test_timeout_satisfied_silence():
    tracker = SlackBehaviorTracker(db, analyzer)

    # Start tracking
    await tracker.on_bot_response("resp_789", "thread_123")

    # Wait for timeout (use shorter delay for test)
    await asyncio.sleep(1)

    # Check signal recorded
    signal = await db.query(BehavioralSignal).filter_by(
        response_id="resp_789",
        signal_type="satisfied_silence"
    ).first()

    assert signal is not None
```

## Integration Test

```python
@pytest.mark.asyncio
async def test_full_thread_flow():
    # Simulate conversation
    tracker = SlackBehaviorTracker(db, analyzer)

    # Bot responds
    await tracker.on_bot_response("resp_100", "thread_500")

    # User asks follow-up
    await tracker.on_thread_message({
        "thread_ts": "thread_500",
        "text": "What about weekends?",
        "user": "U123"
    })

    # User says thanks
    await tracker.on_thread_message({
        "thread_ts": "thread_500",
        "text": "Thanks!",
        "user": "U123"
    })

    # Check signals
    signals = await db.query(BehavioralSignal).filter_by(
        response_id="resp_100"
    ).all()

    signal_types = [s.signal_type for s in signals]
    assert "follow_up" in signal_types
    assert "thanks" in signal_types
```

## Success Criteria

- [ ] Gratitude detected accurately
- [ ] Frustration detected accurately
- [ ] Follow-up questions detected
- [ ] Reactions tracked correctly
- [ ] Timeout works for satisfied silence
- [ ] Signals linked to responses
