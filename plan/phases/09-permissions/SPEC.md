# Phase 09: Permission Checking

## Overview

Filter search results based on user's Confluence permissions, with account linking flow.

## Dependencies

- **Requires**: Phase 08 (Slack Bot)
- **Blocks**: None

## Deliverables

```
src/knowledge_base/
├── auth/
│   ├── __init__.py
│   ├── confluence_link.py    # User account linking
│   └── cache.py              # Permission caching
├── confluence/
│   └── permissions.py        # Permission checker
```

## Technical Specification

### User-Confluence Linking

```python
class UserLink(Base):
    __tablename__ = "user_confluence_links"

    id: int
    slack_user_id: str            # Slack user ID (unique)
    confluence_account_id: str    # Confluence account ID
    confluence_token: str         # Encrypted OAuth token
    linked_at: datetime
    last_used_at: datetime
```

### Linking Flow

```
User: /ask How do I access HR docs?

Bot: ⚠️ To search the knowledge base, please link your Confluence account first.
     [🔗 Link Confluence Account]

(User clicks button → OAuth flow → Token stored)

User: /ask How do I access HR docs?

Bot: (Searches with user's permissions, returns filtered results)
```

### Permission Checker

```python
class PermissionChecker:
    def __init__(self, cache: PermissionCache):
        self.cache = cache

    async def filter_results(
        self,
        user_id: str,
        results: list[SearchResult]
    ) -> list[SearchResult]:
        """Filter results to only those user can access."""
        filtered = []

        for result in results:
            can_access = await self.can_access(user_id, result.page_id)
            if can_access:
                filtered.append(result)

        return filtered

    async def can_access(self, user_id: str, page_id: str) -> bool:
        # Check cache first
        cached = await self.cache.get(user_id, page_id)
        if cached is not None:
            return cached

        # Query Confluence
        user_token = await self.get_user_token(user_id)
        can_access = await self.check_confluence(user_token, page_id)

        # Cache result
        await self.cache.set(user_id, page_id, can_access)
        return can_access
```

### Permission Cache

```python
class PermissionCache:
    def __init__(self, redis: Redis, ttl_seconds: int = 300):
        self.redis = redis
        self.ttl = ttl_seconds

    async def get(self, user_id: str, page_id: str) -> bool | None:
        key = f"perm:{user_id}:{page_id}"
        value = await self.redis.get(key)
        if value is None:
            return None
        return value == b"1"

    async def set(self, user_id: str, page_id: str, can_access: bool):
        key = f"perm:{user_id}:{page_id}"
        await self.redis.setex(key, self.ttl, "1" if can_access else "0")

    async def invalidate_user(self, user_id: str):
        """Clear all cached permissions for user (on re-auth)."""
        pattern = f"perm:{user_id}:*"
        keys = await self.redis.keys(pattern)
        if keys:
            await self.redis.delete(*keys)
```

### OAuth Flow

```python
@app.action("link_confluence")
async def handle_link_confluence(ack, body, client):
    await ack()
    user_id = body["user"]["id"]

    # Generate OAuth URL
    oauth_url = confluence_oauth.get_authorization_url(
        state=user_id  # Pass Slack user ID through OAuth
    )

    await client.chat_postEphemeral(
        channel=body["channel"]["id"],
        user=user_id,
        text=f"Please <{oauth_url}|click here> to link your Confluence account."
    )

@router.get("/auth/confluence/callback")
async def confluence_callback(code: str, state: str):
    """Handle OAuth callback from Confluence."""
    slack_user_id = state
    tokens = await confluence_oauth.exchange_code(code)

    # Get Confluence account ID
    account_id = await confluence_oauth.get_account_id(tokens.access_token)

    # Store encrypted token
    await user_links.create_or_update(
        slack_user_id=slack_user_id,
        confluence_account_id=account_id,
        confluence_token=encrypt(tokens.access_token)
    )

    return RedirectResponse("/auth/success")
```

### Integration with Search

```python
async def search_with_permissions(
    query: str,
    slack_user_id: str
) -> RAGResponse:
    # Check if user is linked
    if not await user_links.is_linked(slack_user_id):
        return RAGResponse(
            answer=None,
            needs_linking=True
        )

    # Get results
    results = await retriever.search(query)

    # Filter by permissions
    permitted_results = await permission_checker.filter_results(
        slack_user_id,
        results
    )

    # Generate answer from permitted results only
    return await rag_chain.answer(query, results=permitted_results)
```

## Definition of Done

- [ ] Account linking flow works
- [ ] Permissions cached in Redis
- [ ] Results filtered correctly
- [ ] User A sees different results than User B
- [ ] Cache invalidates on re-auth
