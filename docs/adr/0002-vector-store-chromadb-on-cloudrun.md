# ADR-0002: Use ChromaDB on Cloud Run Instead of Vertex AI Vector Search

## Status
Superseded by [ADR-0009](0009-neo4j-graphiti-knowledge-store.md)

> **Note**: This ADR has been superseded. The project migrated from ChromaDB to Neo4j + Graphiti as the primary knowledge store. See ADR-0009 for details.

## Date
2024-12-24

## Context
The application requires a vector database for semantic search over document embeddings. We needed to choose between:

1. **Vertex AI Vector Search** - GCP-native managed vector search
2. **ChromaDB on Cloud Run** - Open-source vector database
3. **Pinecone** - Third-party managed vector database
4. **Weaviate** - Open-source alternative

### Requirements
- Semantic similarity search for RAG
- Document collection: <100K chunks expected
- Query latency: <500ms acceptable
- Cost-sensitive deployment

## Decision
We chose **ChromaDB deployed on Cloud Run with Cloud Storage persistence**.

## Rationale

### Cost Comparison
| Option | Monthly Cost | Notes |
|--------|-------------|-------|
| ChromaDB on Cloud Run | ~$15-25 | 1-3 instances, 2GB RAM |
| Vertex AI Vector Search | ~$100-200 | Minimum deployment |
| Pinecone (Starter) | ~$70 | 1M vectors |

### Why ChromaDB?
1. **Cost-effective**: 4-8x cheaper than Vertex AI Vector Search
2. **Simple API**: Native Python client, easy integration
3. **Portable**: No vendor lock-in, can migrate to other providers
4. **Sufficient for scale**: Handles millions of vectors efficiently

### Why Cloud Run?
1. **Managed infrastructure**: Auto-scaling, health checks
2. **Container-native**: Official ChromaDB Docker image available
3. **VPC integration**: Private access from other services
4. **Cloud Storage mounting**: Persistent data via GCS FUSE

### Trade-offs Accepted
- **No hybrid search**: ChromaDB lacks built-in BM25 (keyword) search
- **Manual scaling**: Must configure min/max instances
- **Cold start**: Possible latency on scale-up (mitigated by min_instances=1)

## Consequences

### Positive
- Low operational cost (~$15-25/month)
- No vendor lock-in (ChromaDB is open-source)
- Simple deployment and operations
- Familiar API for developers

### Negative
- No native hybrid search (vector + keyword)
- Less advanced features than Vertex AI Vector Search
- Must manage persistence via Cloud Storage

### Migration Path
If advanced features are needed:
1. Export embeddings from ChromaDB
2. Create Vertex AI Vector Search index
3. Update retriever client to use Vertex AI SDK
4. The `VectorRetriever` abstraction layer minimizes code changes

## Alternatives Considered

### Vertex AI Vector Search
- **Pros**: Managed, scalable, advanced features (filtering, hybrid)
- **Cons**: High minimum cost (~$100/month), GCP lock-in
- **Verdict**: Overkill for current scale

### Pinecone
- **Pros**: Fully managed, good developer experience
- **Cons**: Third-party dependency, higher cost
- **Verdict**: Unnecessary complexity

## References
- [ChromaDB Documentation](https://docs.trychroma.com/)
- [Vertex AI Vector Search Pricing](https://cloud.google.com/vertex-ai/pricing#vector-search)
- [Cloud Run Pricing](https://cloud.google.com/run/pricing)
