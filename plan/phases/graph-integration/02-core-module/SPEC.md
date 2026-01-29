# Phase 2: Core Graph Module - Specification

## Goal
Implement the core logic for interacting with Graphiti, replacing the existing NetworkX/SQLAlchemy based graph implementation.

## Tasks

### 2.1 Graphiti Client Factory
Create `src/knowledge_base/graph/graphiti_client.py`:
- Handle initialization of Graphiti client.
- Switch between Kuzu and Neo4j backends based on config.
- Configure LLM client (reuse Anthropic settings).

### 2.2 Entity Schemas
Create `src/knowledge_base/graph/entity_schemas.py`:
- Define Pydantic models for domain entities: `DocumentEntity`, `PersonEntity`, `TeamEntity`, `ProductEntity`, `TopicEntity`.
- Ensure parity or mapping with existing `EntityType` enum.

### 2.3 Graph Builder (Ingestion)
Create `src/knowledge_base/graph/graphiti_builder.py`:
- Replace functionality of `graph_builder.py`.
- Use `graphiti.add_episode()` for ingesting document content.
- Add bi-temporal metadata (`event_time` = `page.updated_at`).
- **Strategy**: Keep existing `EntityResolver` logic as a post-processing or pre-processing layer to preserve domain specific alias logic if Graphiti's isn't sufficient yet.

### 2.4 Graph Retriever (Search)
Create `src/knowledge_base/graph/graphiti_retriever.py`:
- Replace functionality of `graph_retriever.py`.
- Wrap `graphiti.search()` for hybrid retrieval.
- Maintain interface compatibility with the rest of the system (Dependency Injection).

### 2.5 Chunk-Level Entity Linking
- Enhance the ingestion to link specific *chunks* to entities, not just pages.
- Create `chunk_id -> entity` edges.

## Success Criteria
- Can ingest documents into Graphiti.
- Can retrieve related entities via API.
- Chunk-level resolution is possible.
