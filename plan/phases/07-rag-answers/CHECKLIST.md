# Phase 07: RAG Answer Generation - Checklist

## Pre-Implementation
- [ ] Read SPEC.md completely
- [ ] Verify Phase 06 is complete
- [ ] Add sentence-transformers to dependencies

## Implementation Tasks

### 1. Prompt Templates
- [ ] Create `rag/prompts.py`
- [ ] Define ANSWER_PROMPT template
- [ ] Add system instructions
- [ ] Include citation format guidelines

### 2. Reranker
- [ ] Create `rag/reranker.py`
- [ ] Initialize CrossEncoder model
- [ ] Implement `rerank()` method
- [ ] Handle model loading errors

### 3. RAG Chain
- [ ] Create `rag/chain.py`
- [ ] Implement `answer()` method
- [ ] Build context from results
- [ ] Integrate reranker
- [ ] Parse LLM response

### 4. Context Building
- [ ] Format documents for prompt
- [ ] Include page titles and URLs
- [ ] Add freshness info (last updated)
- [ ] Truncate if too long

### 5. Response Handling
- [ ] Define RAGResponse schema
- [ ] Extract citations from answer
- [ ] Add confidence scoring (optional)
- [ ] Generate warnings for old sources

### 6. API Integration
- [ ] Add `include_answer` parameter
- [ ] Return answer in response
- [ ] Handle generation errors

## Post-Implementation
- [ ] Run tests from TEST.md
- [ ] Update PROGRESS.md status to ✅ Done
- [ ] Commit: "feat(phase-07): RAG answers"
