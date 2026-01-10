# Phase 05.5: Hybrid Search - Test Plan

## Quick Verification

```bash
# Build BM25 index
python -m knowledge_base.cli search rebuild-bm25

# Test search
python -m knowledge_base.cli search query "PTO policy" --verbose
```

## Functional Tests

### 1. BM25 Exact Match
```bash
# Test abbreviation search (BM25 should excel)
python -c "
from knowledge_base.search.bm25 import BM25Index

index = BM25Index()
index.load()  # Load from disk

results = index.search('GCP', k=5)
print('BM25 results for \"GCP\":')
for chunk_id, score in results:
    print(f'  {chunk_id}: {score:.4f}')
"
# Expected: Documents containing "GCP" ranked high
```

### 2. Vector Semantic Search
```bash
# Test semantic query (vector should excel)
python -c "
from knowledge_base.vectorstore.client import ChromaClient
from knowledge_base.vectorstore.embeddings import OllamaEmbeddings
import asyncio

async def test():
    embeddings = OllamaEmbeddings()
    client = ChromaClient()

    query_emb = await embeddings.embed(['how to take time off work'])
    results = client.collection.query(
        query_embeddings=query_emb,
        n_results=5
    )

    print('Vector results for \"how to take time off work\":')
    for doc in results['documents'][0]:
        print(f'  {doc[:80]}...')

asyncio.run(test())
"
```

### 3. Hybrid Combination
```bash
# Test hybrid search
python -c "
from knowledge_base.search.hybrid import HybridRetriever
import asyncio

async def test():
    retriever = HybridRetriever()

    results = await retriever.search(
        'PTO policy vacation',
        k=5,
        bm25_weight=0.3,
        vector_weight=0.7
    )

    print('Hybrid results:')
    for r in results:
        print(f'  {r.chunk_id}: {r.score:.4f}')

asyncio.run(test())
"
```

### 4. Abbreviation vs Semantic
```bash
# Compare results for abbreviation query
echo "=== BM25 only ==="
python -m knowledge_base.cli search query "PTO" --method=bm25

echo "=== Vector only ==="
python -m knowledge_base.cli search query "PTO" --method=vector

echo "=== Hybrid ==="
python -m knowledge_base.cli search query "PTO" --method=hybrid
```

### 5. Weight Sensitivity
```bash
# Test different weight combinations
for weights in "0.1,0.9" "0.3,0.7" "0.5,0.5" "0.7,0.3"; do
    echo "=== Weights: $weights ==="
    python -m knowledge_base.cli search query "how to deploy" --weights=$weights --top=3
done
```

## Unit Tests

```python
# tests/test_hybrid_search.py
import pytest
from knowledge_base.search.bm25 import BM25Index
from knowledge_base.search.fusion import reciprocal_rank_fusion
from knowledge_base.search.hybrid import HybridRetriever

def test_bm25_tokenize():
    index = BM25Index()
    tokens = index.tokenize("Hello World!")
    assert tokens == ["hello", "world!"]

def test_rrf_fusion():
    list1 = [("doc1", 1.0), ("doc2", 0.8), ("doc3", 0.6)]
    list2 = [("doc2", 1.0), ("doc1", 0.7), ("doc4", 0.5)]

    combined = reciprocal_rank_fusion(list1, list2)

    # doc1 and doc2 should be top (appear in both)
    top_ids = [doc_id for doc_id, _ in combined[:2]]
    assert "doc1" in top_ids
    assert "doc2" in top_ids

def test_bm25_exact_match():
    index = BM25Index()
    # Mock corpus
    chunks = [
        MockChunk("c1", "GCP cloud platform"),
        MockChunk("c2", "AWS services"),
        MockChunk("c3", "Google Cloud Platform GCP"),
    ]
    index.build(chunks)

    results = index.search("GCP", k=3)
    top_ids = [doc_id for doc_id, _ in results]

    # Docs with "GCP" should rank higher
    assert top_ids[0] in ["c1", "c3"]

@pytest.mark.asyncio
async def test_hybrid_retriever():
    retriever = HybridRetriever()
    results = await retriever.search("test query", k=5)
    assert len(results) <= 5
```

## Success Criteria

- [ ] BM25 index builds successfully
- [ ] Abbreviation queries find exact matches
- [ ] Semantic queries find conceptual matches
- [ ] Hybrid combines both effectively
- [ ] Configurable weights work correctly
