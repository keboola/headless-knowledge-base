# Phase 07: RAG Answer Generation

## Overview

Generate natural language answers from retrieved documents using LLM, with source citations.

## Dependencies

- **Requires**: Phase 06 (Search API)
- **Blocks**: Phase 08 (Slack Bot)

## Deliverables

```
src/knowledge_base/
├── rag/
│   ├── chain.py              # RAG orchestration
│   ├── prompts.py            # Prompt templates
│   └── reranker.py           # Cross-encoder reranking
```

## Technical Specification

### RAG Chain

```python
class RAGChain:
    def __init__(
        self,
        retriever: Retriever,
        llm: BaseLLM,
        reranker: Reranker | None = None
    ):
        self.retriever = retriever
        self.llm = llm
        self.reranker = reranker

    async def answer(
        self,
        query: str,
        top_k: int = 5,
        include_sources: bool = True
    ) -> RAGResponse:
        # 1. Retrieve relevant chunks
        results = await self.retriever.search(query, top_k=top_k * 2)

        # 2. Rerank if available
        if self.reranker:
            results = await self.reranker.rerank(query, results, top_k=top_k)
        else:
            results = results[:top_k]

        # 3. Build context
        context = self.build_context(results)

        # 4. Generate answer
        prompt = ANSWER_PROMPT.format(
            context=context,
            query=query
        )
        answer = await self.llm.generate(prompt)

        return RAGResponse(
            answer=answer,
            sources=results if include_sources else [],
            query=query
        )
```

### Answer Prompt

```python
ANSWER_PROMPT = """You are Keboola's knowledge base assistant.
Answer based ONLY on the provided context documents.

Context:
{context}

Question: {query}

Guidelines:
1. Cite sources using [Page Title](url) format
2. If sources are outdated (>1 year), mention this
3. If you can't find the answer, say "I couldn't find this in the knowledge base"
4. Never invent information not in the context
5. Be concise but complete

Answer:"""
```

### Cross-Encoder Reranker

```python
from sentence_transformers import CrossEncoder

class Reranker:
    def __init__(self, model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        self.model = CrossEncoder(model)

    async def rerank(
        self,
        query: str,
        results: list[SearchResult],
        top_k: int = 5
    ) -> list[SearchResult]:
        """Rerank results using cross-encoder."""
        pairs = [(query, r.content) for r in results]
        scores = self.model.predict(pairs)

        # Sort by reranker score
        reranked = sorted(
            zip(results, scores),
            key=lambda x: x[1],
            reverse=True
        )

        return [r for r, _ in reranked[:top_k]]
```

### Response Schema

```python
class RAGResponse(BaseModel):
    answer: str
    sources: list[SearchResult]
    query: str
    confidence: float | None = None      # Optional confidence score
    warnings: list[str] = []             # e.g., "Sources may be outdated"
```

### Updated Search Endpoint

```python
@router.post("/api/v1/search")
async def search(request: SearchRequest):
    # ... existing search logic ...

    # If include_answer requested
    if request.include_answer:
        rag_response = await rag_chain.answer(
            query=request.query,
            top_k=request.top_k
        )
        return SearchResponse(
            query=request.query,
            answer=rag_response.answer,
            sources=rag_response.sources,
            warnings=rag_response.warnings
        )
```

## Configuration

LLM provider is configured via `.env` file or environment variables.
See Phase 04 SPEC for full configuration options.

The RAG chain uses the factory pattern to obtain the configured LLM:

```python
from knowledge_base.rag.factory import get_llm

llm = await get_llm()  # Returns configured provider (Claude or Ollama)
```

Key configuration variables:
- `LLM_PROVIDER`: Select provider ('claude', 'ollama', or empty for auto-select)
- `ANTHROPIC_API_KEY`: Required for Claude provider
- `OLLAMA_BASE_URL`: URL for Ollama server

## Definition of Done

- [ ] RAG chain generates coherent answers
- [ ] Sources cited correctly with links
- [ ] Reranker improves relevance
- [ ] Handles "no answer found" gracefully
- [ ] Warns about outdated sources
