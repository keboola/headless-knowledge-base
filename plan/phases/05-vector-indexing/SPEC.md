# Phase 05: Vector Indexing

## Overview

Create embeddings for all chunks and store them in ChromaDB for semantic search.

## Dependencies

- **Requires**: Phase 04 (Metadata Generation)
- **Blocks**: Phase 06 (Search API)
- **Parallel**: Phase 05.5 (Hybrid Search)

## Deliverables

```
src/knowledge_base/
├── vectorstore/
│   ├── __init__.py
│   ├── embeddings.py         # Ollama embeddings
│   ├── client.py             # ChromaDB client
│   └── indexer.py            # Indexing logic
```

## Technical Specification

### Embeddings Interface

```python
class BaseEmbeddings(ABC):
    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for texts."""

class OllamaEmbeddings(BaseEmbeddings):
    def __init__(self, model: str = "mxbai-embed-large"):
        self.model = model
        self.client = httpx.AsyncClient()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        embeddings = []
        for text in texts:
            response = await self.client.post(
                f"{OLLAMA_URL}/api/embeddings",
                json={"model": self.model, "prompt": text}
            )
            embeddings.append(response.json()["embedding"])
        return embeddings
```

### ChromaDB Client

```python
class ChromaClient:
    def __init__(self, host: str, port: int):
        self.client = chromadb.HttpClient(host=host, port=port)
        self.collection = self.client.get_or_create_collection(
            name="confluence_documents",
            metadata={"hnsw:space": "cosine"}
        )

    async def upsert(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict]
    ):
        """Insert or update documents."""
        self.collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas
        )

    async def delete(self, ids: list[str]):
        """Delete documents by ID."""
        self.collection.delete(ids=ids)
```

### Indexer

```python
class VectorIndexer:
    def __init__(self, embeddings: BaseEmbeddings, chroma: ChromaClient):
        self.embeddings = embeddings
        self.chroma = chroma

    async def index_chunks(self, chunks: list[Chunk], batch_size: int = 100):
        """Index chunks with their metadata."""
        for batch in batched(chunks, batch_size):
            texts = [c.content for c in batch]
            embeddings = await self.embeddings.embed(texts)

            ids = [c.chunk_id for c in batch]
            metadatas = [self.build_metadata(c) for c in batch]

            await self.chroma.upsert(
                ids=ids,
                embeddings=embeddings,
                documents=texts,
                metadatas=metadatas
            )

    def build_metadata(self, chunk: Chunk) -> dict:
        """Build ChromaDB metadata from chunk and its metadata."""
        return {
            "page_id": chunk.page_id,
            "page_title": chunk.page_title,
            "space_key": chunk.space_key,
            "chunk_type": chunk.chunk_type,
            "topics": json.dumps(chunk.metadata.topics),
            "doc_type": chunk.metadata.doc_type,
            "author": chunk.author,
            "updated_at": chunk.updated_at.isoformat(),
        }
```

### ChromaDB Metadata Schema

| Field | Type | Description |
|-------|------|-------------|
| page_id | string | Confluence page ID |
| page_title | string | Page title |
| space_key | string | Space key |
| chunk_type | string | text, code, table |
| topics | string (JSON) | Topic list |
| doc_type | string | policy, how-to, etc. |
| author | string | Last modifier |
| updated_at | string | ISO datetime |

### CLI Command

```bash
# Index all chunks
python -m knowledge_base.cli index

# Index specific space
python -m knowledge_base.cli index --space=ENG

# Reindex all (delete and rebuild)
python -m knowledge_base.cli index --reindex
```

## Configuration

```bash
CHROMA_HOST=chromadb
CHROMA_PORT=8000
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_EMBEDDING_MODEL=mxbai-embed-large
INDEX_BATCH_SIZE=100
```

## Definition of Done

- [ ] All chunks embedded and indexed
- [ ] Metadata stored with embeddings
- [ ] ChromaDB collection queryable
- [ ] Idempotent: re-run upserts (no duplicates)
- [ ] Deleted chunks removed from index
