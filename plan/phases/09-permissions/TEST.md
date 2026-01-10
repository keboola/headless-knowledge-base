# Phase 09: Permission Checking - Test Plan

## Prerequisites

Need two Confluence accounts:
- **User A**: Has access to HR space
- **User B**: Does NOT have access to HR space

## Quick Verification

```
As User A (with HR access):
> /ask What is the HR policy?
Expected: Returns HR-related documents

As User B (without HR access):
> /ask What is the HR policy?
Expected: Does NOT return HR documents, or says "no results found"
```

## Functional Tests

### 1. Account Linking Flow
```
As new user (not linked):
> /ask test question

Expected:
- Message about linking account
- Button to start OAuth flow
- No results returned

(Click link button, complete OAuth)

> /ask test question
Expected: Results returned normally
```

### 2. Permission Filtering
```
Setup:
- Document "HR Policy" in HR space (restricted)
- Document "Company Handbook" in public space

As User A (HR access):
> /ask company policies
Expected: Both HR Policy and Company Handbook appear

As User B (no HR access):
> /ask company policies
Expected: Only Company Handbook appears
```

### 3. Cache Behavior
```bash
# Check Redis cache after query
redis-cli keys "perm:*"
# Expected: Permission cache entries

# Verify TTL
redis-cli ttl "perm:U123ABC:page_456"
# Expected: ~300 seconds (or configured TTL)
```

### 4. Cache Invalidation
```
1. User queries and results are cached
2. User re-links account
3. Query again

Expected: Fresh permission check (cache cleared)
```

### 5. Unlinked User Experience
```
As unlinked user:
> /ask anything

Expected:
- Friendly message explaining need to link
- Clear instructions
- Link button
```

## Unit Tests

```python
# tests/test_permissions.py
import pytest
from knowledge_base.confluence.permissions import PermissionChecker
from knowledge_base.auth.cache import PermissionCache

@pytest.mark.asyncio
async def test_cache_hit():
    cache = PermissionCache(redis_client)
    await cache.set("user1", "page1", True)

    result = await cache.get("user1", "page1")
    assert result is True

@pytest.mark.asyncio
async def test_cache_miss():
    cache = PermissionCache(redis_client)
    result = await cache.get("user1", "nonexistent")
    assert result is None

@pytest.mark.asyncio
async def test_filter_results():
    checker = PermissionChecker(cache)

    # Mock: user can access page1 but not page2
    async def mock_can_access(user_id, page_id):
        return page_id == "page1"

    checker.can_access = mock_can_access

    results = [
        MockResult("page1", "Allowed"),
        MockResult("page2", "Forbidden"),
    ]

    filtered = await checker.filter_results("user1", results)

    assert len(filtered) == 1
    assert filtered[0].page_id == "page1"

@pytest.mark.asyncio
async def test_cache_invalidation():
    cache = PermissionCache(redis_client)

    # Set some permissions
    await cache.set("user1", "page1", True)
    await cache.set("user1", "page2", False)

    # Invalidate
    await cache.invalidate_user("user1")

    # Should be cleared
    assert await cache.get("user1", "page1") is None
    assert await cache.get("user1", "page2") is None
```

## Integration Test

```python
@pytest.mark.asyncio
async def test_end_to_end_permissions():
    # User A with HR access
    user_a_results = await search_with_permissions(
        "HR policy",
        slack_user_id="USER_A"
    )

    # User B without HR access
    user_b_results = await search_with_permissions(
        "HR policy",
        slack_user_id="USER_B"
    )

    # User A should see more results
    hr_pages_a = [r for r in user_a_results if r.space_key == "HR"]
    hr_pages_b = [r for r in user_b_results if r.space_key == "HR"]

    assert len(hr_pages_a) > 0
    assert len(hr_pages_b) == 0
```

## Success Criteria

- [ ] OAuth linking flow complete
- [ ] Permissions correctly filter results
- [ ] Cache reduces API calls
- [ ] Different users see different results
- [ ] Unlinked users prompted to link
- [ ] Cache invalidates on re-auth
