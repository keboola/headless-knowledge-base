# Phase 05: Vector Indexing - Test Plan

## Quick Verification

```bash
# Verify Ollama embedding model
curl http://localhost:11434/api/tags | jq '.models[] | select(.name | contains("mxbai"))'

# Run indexing
python -m knowledge_base.cli index --verbose

# Check ChromaDB collection
curl http://localhost:8001/api/v1/collections/confluence_documents | jq
```

## Functional Tests

### 1. Embedding Generation
```bash
# Test embedding
python -c "
from knowledge_base.vectorstore.embeddings import OllamaEmbeddings
import asyncio

async def test():
    embeddings = OllamaEmbeddings()
    result = await embeddings.embed(['Test document content'])
    print(f'Embedding dimensions: {len(result[0])}')
    print(f'First 5 values: {result[0][:5]}')

asyncio.run(test())
"
# Expected: 1024 dimensions for mxbai-embed-large
```

### 2. Index Count
```bash
# Check document count matches chunks
CHUNK_COUNT=$(sqlite3 knowledge_base.db "SELECT COUNT(*) FROM chunks;")
INDEX_COUNT=$(curl -s http://localhost:8001/api/v1/collections/confluence_documents | jq '.count')

echo "Chunks: $CHUNK_COUNT, Indexed: $INDEX_COUNT"
[ "$CHUNK_COUNT" = "$INDEX_COUNT" ] && echo "PASS" || echo "FAIL"
```

### 3. Metadata Stored
```bash
# Query with metadata filter
python -c "
from knowledge_base.vectorstore.client import ChromaClient
client = ChromaClient()

results = client.collection.get(
    limit=5,
    include=['metadatas']
)
for meta in results['metadatas']:
    print(f\"Page: {meta.get('page_title')}, Type: {meta.get('doc_type')}\")
"
```

### 4. Similarity Search
```bash
# Test vector search
python -c "
from knowledge_base.vectorstore.client import ChromaClient
from knowledge_base.vectorstore.embeddings import OllamaEmbeddings
import asyncio

async def test():
    embeddings = OllamaEmbeddings()
    client = ChromaClient()

    query_embedding = await embeddings.embed(['How do I request time off?'])

    results = client.collection.query(
        query_embeddings=query_embedding,
        n_results=3
    )

    print('Top 3 results:')
    for i, doc in enumerate(results['documents'][0]):
        print(f'{i+1}. {doc[:100]}...')

asyncio.run(test())
"
```

### 5. Idempotency
```bash
# Index twice
python -m knowledge_base.cli index
COUNT1=$(curl -s http://localhost:8001/api/v1/collections/confluence_documents | jq '.count')

python -m knowledge_base.cli index
COUNT2=$(curl -s http://localhost:8001/api/v1/collections/confluence_documents | jq '.count')

[ "$COUNT1" = "$COUNT2" ] && echo "PASS: Idempotent" || echo "FAIL: Duplicates created"
```

## Unit Tests

```python
# tests/test_vectorstore.py
import pytest
from knowledge_base.vectorstore.embeddings import OllamaEmbeddings
from knowledge_base.vectorstore.client import ChromaClient

@pytest.mark.asyncio
async def test_embed_single():
    embeddings = OllamaEmbeddings()
    result = await embeddings.embed(["test"])
    assert len(result) == 1
    assert len(result[0]) == 1024  # mxbai-embed-large dimension

@pytest.mark.asyncio
async def test_embed_batch():
    embeddings = OllamaEmbeddings()
    result = await embeddings.embed(["test1", "test2", "test3"])
    assert len(result) == 3

def test_chroma_upsert():
    client = ChromaClient()
    client.upsert(
        ids=["test_1"],
        embeddings=[[0.1] * 1024],
        documents=["Test document"],
        metadatas=[{"page_id": "test"}]
    )
    assert client.collection.count() >= 1
```

## Success Criteria

- [ ] All chunks indexed
- [ ] Embedding dimensions correct (1024)
- [ ] Metadata queryable
- [ ] Similarity search returns relevant results
- [ ] No duplicate entries on re-index
