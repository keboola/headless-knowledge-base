# Phase 04: Metadata Generation - Checklist

## Pre-Implementation
- [ ] Read SPEC.md completely
- [ ] Verify Phase 03 is complete
- [ ] Pull Ollama model: `ollama pull llama3.1:8b`
- [ ] Test Ollama is accessible

## Implementation Tasks

### 1. LLM Wrapper
- [ ] Create `rag/__init__.py`
- [ ] Create `rag/llm.py` with BaseLLM interface
- [ ] Implement OllamaLLM class
- [ ] Test basic generation

### 2. Database Model
- [ ] Add ChunkMetadata model to `db/models.py`
- [ ] Run migrations / create table
- [ ] Test metadata storage

### 3. Metadata Schemas
- [ ] Create `metadata/__init__.py`
- [ ] Create `metadata/schemas.py` with Pydantic models
- [ ] Define DocumentMetadata schema
- [ ] Add JSON parsing helpers

### 4. Vocabulary Normalizer
- [ ] Create `metadata/normalizer.py`
- [ ] Define TOPIC_SYNONYMS mapping
- [ ] Define AUDIENCE_CANONICAL list
- [ ] Implement `normalize_topics()`
- [ ] Implement `normalize_audience()`

### 5. Metadata Extractor
- [ ] Create `metadata/extractor.py`
- [ ] Define METADATA_EXTRACTION_PROMPT
- [ ] Implement `extract()` method
- [ ] Add JSON response parsing
- [ ] Handle LLM errors gracefully
- [ ] Add retry logic

### 6. Batch Processing
- [ ] Implement batch metadata generation
- [ ] Add progress tracking
- [ ] Handle partial failures
- [ ] Implement resume capability

### 7. CLI Command
- [ ] Add `metadata` command to CLI
- [ ] Add `--space` filter
- [ ] Add `--regenerate` flag
- [ ] Add `--batch-size` option

## Post-Implementation
- [ ] Run tests from TEST.md
- [ ] Update PROGRESS.md status to ✅ Done
- [ ] Commit: "feat(phase-04): metadata generation"
