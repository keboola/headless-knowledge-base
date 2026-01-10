# Phase 07: RAG Answer Generation - Test Plan

## Quick Verification

```bash
curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "How do I request PTO?",
    "include_answer": true
  }' | jq '.answer'
```

## Functional Tests

### 1. Answer Generation
```bash
curl -s -X POST http://localhost:8000/api/v1/search \
  -d '{
    "query": "What is the vacation policy?",
    "include_answer": true
  }' | jq '{answer: .answer, source_count: (.sources | length)}'
# Expected: Coherent answer with sources
```

### 2. Citation Format
```bash
curl -s -X POST http://localhost:8000/api/v1/search \
  -d '{
    "query": "How do I deploy to production?",
    "include_answer": true
  }' | jq '.answer' | grep -o '\[.*\](http.*)'
# Expected: Citations in [Title](url) format
```

### 3. No Answer Scenario
```bash
curl -s -X POST http://localhost:8000/api/v1/search \
  -d '{
    "query": "What is the meaning of life?",
    "include_answer": true
  }' | jq '.answer'
# Expected: "I couldn't find this in the knowledge base" or similar
```

### 4. Outdated Source Warning
```bash
# Query known old content
curl -s -X POST http://localhost:8000/api/v1/search \
  -d '{
    "query": "old policy from 2020",
    "include_answer": true
  }' | jq '.warnings'
# Expected: Warning about outdated sources
```

### 5. Reranker Impact
```bash
# Compare with and without reranker
echo "=== Without Reranker ==="
curl -s -X POST http://localhost:8000/api/v1/search \
  -d '{"query": "onboarding", "top_k": 3, "use_reranker": false}' | jq '.results[].page_title'

echo "=== With Reranker ==="
curl -s -X POST http://localhost:8000/api/v1/search \
  -d '{"query": "onboarding", "top_k": 3, "use_reranker": true}' | jq '.results[].page_title'
```

## Unit Tests

```python
# tests/test_rag.py
import pytest
from knowledge_base.rag.chain import RAGChain
from knowledge_base.rag.reranker import Reranker

@pytest.mark.asyncio
async def test_rag_answer():
    chain = RAGChain()
    response = await chain.answer("What is PTO?")

    assert response.answer is not None
    assert len(response.answer) > 0
    assert len(response.sources) > 0

@pytest.mark.asyncio
async def test_rag_no_hallucination():
    chain = RAGChain()
    response = await chain.answer("Tell me about dragons")

    # Should not invent information
    assert "couldn't find" in response.answer.lower() or \
           "no information" in response.answer.lower()

def test_reranker():
    reranker = Reranker()

    results = [
        MockResult("doc1", "PTO policy details"),
        MockResult("doc2", "Office locations"),
        MockResult("doc3", "How to request time off"),
    ]

    reranked = reranker.rerank("vacation request", results, top_k=2)

    # PTO and time off should rank higher than office locations
    titles = [r.content for r in reranked]
    assert "Office locations" not in titles

@pytest.mark.asyncio
async def test_answer_has_citations():
    chain = RAGChain()
    response = await chain.answer("onboarding process")

    # Check for citation format
    assert "[" in response.answer and "](" in response.answer
```

## Success Criteria

- [ ] Answers are coherent and relevant
- [ ] Sources correctly cited with links
- [ ] Reranker improves answer quality
- [ ] No hallucination (only uses context)
- [ ] Warns about old sources
- [ ] Handles no-answer gracefully
