# Phase 04: Metadata Generation - Test Plan

## Quick Verification

```bash
# Ensure Ollama model is available
curl http://localhost:11434/api/tags | jq '.models[] | select(.name | contains("llama3.1"))'

# Generate metadata
python -m knowledge_base.cli metadata --verbose

# Check results
sqlite3 knowledge_base.db "SELECT COUNT(*) FROM chunk_metadata;"
```

## Functional Tests

### 1. LLM Connection
```bash
# Test Ollama
python -c "
from knowledge_base.rag.llm import OllamaLLM
import asyncio

async def test():
    llm = OllamaLLM()
    response = await llm.generate('Say hello')
    print(f'LLM response: {response[:100]}')

asyncio.run(test())
"
```

### 2. Metadata Quality
```bash
# Check extracted metadata
sqlite3 knowledge_base.db "
SELECT
    cm.chunk_id,
    cm.topics,
    cm.doc_type,
    SUBSTR(cm.summary, 1, 100) as summary
FROM chunk_metadata cm
LIMIT 5;
"
# Expected: Valid JSON arrays, sensible summaries
```

### 3. Vocabulary Normalization
```bash
# Check topics are normalized
sqlite3 knowledge_base.db "
SELECT DISTINCT json_each.value as topic
FROM chunk_metadata, json_each(chunk_metadata.topics)
ORDER BY topic
LIMIT 20;
"
# Expected: Canonical topic names (no duplicates like "eng" and "engineering")
```

### 4. Coverage
```bash
# Verify all chunks have metadata
sqlite3 knowledge_base.db "
SELECT
    (SELECT COUNT(*) FROM chunks) as total_chunks,
    (SELECT COUNT(*) FROM chunk_metadata) as with_metadata;
"
# Expected: Numbers should match
```

### 5. Doc Type Classification
```bash
# Check doc type distribution
sqlite3 knowledge_base.db "
SELECT doc_type, COUNT(*) as count
FROM chunk_metadata
GROUP BY doc_type
ORDER BY count DESC;
"
# Expected: Reasonable distribution across types
```

## Unit Tests

```python
# tests/test_metadata.py
import pytest
from knowledge_base.metadata.extractor import MetadataExtractor
from knowledge_base.metadata.normalizer import VocabularyNormalizer

def test_normalize_topics():
    normalizer = VocabularyNormalizer()
    result = normalizer.normalize_topics(["eng", "development"])
    assert result == ["engineering"]

def test_normalize_audience():
    normalizer = VocabularyNormalizer()
    result = normalizer.normalize_audience(["new hire", "developers"])
    assert "new_hires" in result

@pytest.mark.asyncio
async def test_extract_metadata():
    extractor = MetadataExtractor()
    content = "This document describes the PTO policy for all employees."
    metadata = await extractor.extract(content, "PTO Policy")

    assert "policy" in metadata.doc_type.lower() or metadata.doc_type == "policy"
    assert len(metadata.topics) > 0
    assert len(metadata.summary) > 0
```

## Success Criteria

- [ ] All chunks have metadata
- [ ] Topics are normalized (no synonyms)
- [ ] doc_type is one of valid types
- [ ] Summaries are < 200 characters
- [ ] No LLM errors in logs
- [ ] Processing time < 5s per chunk (average)
