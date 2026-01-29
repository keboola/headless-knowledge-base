#!/usr/bin/env python3
"""Quick script to test knowledge creation without Slack slash command."""

import asyncio
from knowledge_base.graph.graphiti_indexer import GraphitiIndexer
from knowledge_base.graph.graphiti_retriever import get_graphiti_retriever


async def create_knowledge(fact: str, title: str = "Quick Fact", created_by: str = "test_user"):
    """Create a knowledge chunk directly."""
    print(f"Creating knowledge: {fact[:100]}...")

    indexer = GraphitiIndexer()

    result = await indexer.index_single_chunk(
        content=fact,
        page_title=title,
        source_url="slack://manual-test",
        created_by=created_by,
        metadata={
            "type": "quick_fact",
            "channel_id": "manual_test",
        }
    )

    print(f"✅ Success! Chunk ID: {result.chunk_id}")
    print(f"   Content: {result.content[:150]}...")
    print(f"   Quality Score: {result.quality_score}")
    return result


async def verify_knowledge(search_query: str):
    """Verify the knowledge was indexed."""
    print(f"\n🔍 Searching for: '{search_query}'")

    retriever = get_graphiti_retriever()
    results = await retriever.search(search_query, num_results=3)

    if results:
        print(f"✅ Found {len(results)} matching chunks:")
        for i, result in enumerate(results):
            print(f"\n   {i+1}. {result.content[:100]}...")
            print(f"      Created by: {result.metadata.get('created_by', 'unknown')}")
            print(f"      Quality: {result.metadata.get('quality_score', 'N/A')}")
    else:
        print("❌ No matching chunks found")


async def main():
    # Your HR system knowledge
    hr_fact = """We use for HR (HR information system) headless ODOO. Employees can connect to it using MCP server called ODOO MCP Staging. They just need to click connect in claude.ai interface to access HR system."""

    print("=" * 70)
    print("KNOWLEDGE CREATION TEST")
    print("=" * 70)

    # Create the knowledge
    result = await create_knowledge(
        fact=hr_fact,
        title="HR System - ODOO MCP",
        created_by="jiri.manas"
    )

    # Wait a moment for indexing
    await asyncio.sleep(1)

    # Verify it was indexed
    await verify_knowledge("ODOO HR system")
    await verify_knowledge("MCP server staging")

    print("\n" + "=" * 70)
    print("✅ Test complete! Knowledge should now be searchable by the bot.")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
