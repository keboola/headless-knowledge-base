"""Batch knowledge graph import pipeline.

Uses Gemini Batch API for entity/relationship extraction (1 LLM call per chunk
instead of 7-20), then bulk-imports into Neo4j in Graphiti-compatible schema.
"""
