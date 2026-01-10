# ADR-0003: Use Anthropic Claude API Instead of Vertex AI

## Status
Accepted

## Date
2024-12-24

## Context
The application requires a Large Language Model (LLM) for:
- RAG answer generation
- Metadata extraction from documents
- Quality scoring

We needed to choose between:
1. **Anthropic Claude** - Direct API access
2. **Vertex AI (Gemini)** - GCP-native LLM
3. **Ollama** - Self-hosted open models
4. **Claude via Vertex AI** - Claude through GCP marketplace

### Requirements
- High-quality text generation
- JSON output capability for metadata extraction
- Cost-effective for moderate usage
- Production-ready reliability

## Decision
We chose **Anthropic Claude API (claude-3-5-haiku)** accessed directly via HTTP.

## Rationale

### Why Claude?
1. **Quality**: Excellent instruction following and JSON generation
2. **Cost-effective**: Haiku model is very affordable ($0.25/1M input tokens)
3. **Reliability**: 99.9% uptime SLA from Anthropic
4. **Simplicity**: Direct API, no GCP configuration needed

### Why Not Vertex AI?
1. **Additional complexity**: Requires GCP service account setup
2. **No significant benefit**: Claude API is already cloud-native
3. **Cost similar**: Gemini pricing comparable to Claude Haiku
4. **Lock-in**: Vertex AI ties us to GCP-specific code

### Why Not Ollama?
1. **Not scalable**: Requires dedicated GPU instance
2. **High cost**: GPU instances are expensive (~$200+/month)
3. **Operational burden**: Model updates, monitoring, etc.
4. **Quality gap**: Open models lag behind Claude/GPT-4

### Existing Abstraction
The codebase already has:
- `BaseLLM` abstract class in `src/knowledge_base/rag/llm.py`
- Factory pattern in `src/knowledge_base/rag/factory.py`
- Claude provider in `src/knowledge_base/rag/providers/claude.py`

Adding Vertex AI would require only:
1. New `VertexAILLM` class (~50 lines)
2. Register in factory (~3 lines)
3. Add config variables (~5 lines)

## Consequences

### Positive
- Simple, working solution today
- No GCP-specific code for LLM
- Easy to switch providers via factory pattern
- Cost-effective (~$5-20/month for typical usage)

### Negative
- Third-party dependency (Anthropic)
- Separate billing from GCP
- Data leaves GCP (sent to Anthropic API)

### Security Considerations
- API key stored in GCP Secret Manager
- Data sent to Anthropic is subject to their data policy
- For sensitive data, consider Vertex AI with data residency

### Migration Path
If Vertex AI is required:
```python
# src/knowledge_base/rag/providers/vertex.py
from google.cloud import aiplatform

class VertexAILLM(BaseLLM):
    @property
    def provider_name(self) -> str:
        return "vertex-ai"

    async def generate(self, prompt: str, **kwargs) -> str:
        # Use Vertex AI SDK
        ...
```

Register in factory:
```python
@register_provider("vertex-ai")
def _create_vertex():
    from knowledge_base.rag.providers.vertex import VertexAILLM
    return VertexAILLM()
```

## References
- [Anthropic Claude Pricing](https://www.anthropic.com/pricing)
- [Vertex AI Pricing](https://cloud.google.com/vertex-ai/pricing)
- [Claude API Documentation](https://docs.anthropic.com/claude/reference)
