# Phase 04: Metadata Generation

## Overview

Use LLM to automatically generate rich metadata for each document: topics, intents, audience, document type, and summary.

## Dependencies

- **Requires**: Phase 03 (Content Parsing)
- **Blocks**: Phase 05 (Indexing)
- **Parallel**: Phase 04.5 (Knowledge Graph)

## Deliverables

```
src/knowledge_base/
├── metadata/
│   ├── __init__.py
│   ├── extractor.py         # LLM-based extraction
│   ├── normalizer.py        # Vocabulary normalization
│   └── schemas.py           # Pydantic models
├── rag/
│   ├── __init__.py
│   ├── llm.py               # BaseLLM and OllamaLLM implementation
│   ├── factory.py           # Provider registry and factory (get_llm)
│   ├── exceptions.py        # LLM exception hierarchy
│   └── providers/
│       ├── __init__.py
│       └── claude.py        # Claude/Anthropic implementation
└── db/models.py             # Add ChunkMetadata model
```

## Technical Specification

### Metadata Schema

```python
class ChunkMetadata(Base):
    __tablename__ = "chunk_metadata"

    id: int
    chunk_id: str             # FK to chunks
    topics: str               # JSON: ["onboarding", "benefits"]
    intents: str              # JSON: ["new_employee", "planning_vacation"]
    audience: str             # JSON: ["all_employees", "engineering"]
    doc_type: str             # "policy", "how-to", "reference", "FAQ"
    key_entities: str         # JSON: ["GCP", "Snowflake", "Prague"]
    summary: str              # 1-2 sentence summary
    complexity: str           # "beginner", "intermediate", "advanced"
    generated_at: datetime
```

### LLM Extractor

```python
class MetadataExtractor:
    def __init__(self, llm: BaseLLM):
        self.llm = llm

    async def extract(self, content: str, page_title: str) -> DocumentMetadata:
        prompt = METADATA_EXTRACTION_PROMPT.format(
            title=page_title,
            content=content[:4000]  # Limit context
        )
        response = await self.llm.generate(prompt)
        return self.parse_response(response)
```

### Extraction Prompt

```
Analyze this Confluence document and extract structured metadata.

Title: {title}
Content: {content}

Extract as JSON:
{
    "topics": ["3-5 main topics"],
    "intents": ["2-3 use cases when useful"],
    "audience": ["who should read this"],
    "doc_type": "policy|how-to|reference|FAQ|announcement|meeting-notes",
    "key_entities": ["products, services, tools mentioned"],
    "summary": "1-2 sentence summary",
    "complexity": "beginner|intermediate|advanced"
}
```

### Vocabulary Normalizer

```python
TOPIC_SYNONYMS = {
    "engineering": ["engineers", "eng", "development", "dev"],
    "onboarding": ["new hire", "new employee", "getting started"],
    "benefits": ["perks", "compensation"],
}

AUDIENCE_CANONICAL = [
    "all_employees", "engineering", "sales", "hr",
    "leadership", "new_hires", "managers"
]

class VocabularyNormalizer:
    def normalize_topics(self, raw_topics: list[str]) -> list[str]:
        """Map to canonical forms."""

    def normalize_audience(self, raw_audience: list[str]) -> list[str]:
        """Map to canonical audience values."""
```

### CLI Command

```bash
# Generate metadata for all chunks
python -m knowledge_base.cli metadata

# Generate for specific space
python -m knowledge_base.cli metadata --space=ENG

# Regenerate all (force)
python -m knowledge_base.cli metadata --regenerate
```

## Configuration

Configure via `.env` file or environment variables. Environment variables override file values (12-factor app pattern).

```bash
# LLM Provider Selection
LLM_PROVIDER=claude              # 'claude', 'ollama', or empty for auto-select

# Claude Settings (when LLM_PROVIDER=claude)
ANTHROPIC_API_KEY=sk-ant-...     # Required for Claude
ANTHROPIC_MODEL=claude-3-5-haiku-20241022

# Ollama Settings (when LLM_PROVIDER=ollama)
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_LLM_MODEL=llama3.1:8b

# Common Settings
METADATA_BATCH_SIZE=10
```

### Auto-Selection Logic
When `LLM_PROVIDER` is empty:
1. If `ANTHROPIC_API_KEY` is set → use Claude
2. Otherwise → fall back to Ollama

## Definition of Done

- [ ] All chunks have metadata generated
- [ ] Topics normalized to canonical vocabulary
- [ ] Summaries are concise and accurate
- [ ] doc_type correctly classified
- [ ] Idempotent: re-run updates existing
