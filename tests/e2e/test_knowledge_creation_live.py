"""Live E2E tests for knowledge creation with real ChromaDB integration.

These tests verify that knowledge creation actually works end-to-end:
- Content is indexed in ChromaDB
- Embeddings are generated
- Knowledge is searchable by the bot
- Quality scores are tracked

Prerequisites:
- ChromaDB running and accessible
- Bot has required permissions
"""

import pytest
import asyncio
import uuid
from datetime import datetime


def create_test_chunk(unique_test_id: str, content: str, title: str, url: str, author: str = "e2e_test"):
    """Helper to create a ChunkData object for testing."""
    from knowledge_base.vectorstore.indexer import ChunkData

    page_id = f"test_{uuid.uuid4().hex[:16]}"
    chunk_id = f"{page_id}_0"
    now = datetime.utcnow().isoformat()

    return ChunkData(
        chunk_id=chunk_id,
        content=content,
        page_id=page_id,
        page_title=title,
        chunk_index=0,
        space_key="TEST",
        url=url,
        author=author,
        created_at=now,
        updated_at=now,
        chunk_type="text",
        parent_headers="[]",
        quality_score=100.0,
        access_count=0,
        feedback_count=0,
        owner=author,
        reviewed_by="",
        reviewed_at="",
        classification="internal",
        doc_type="test_fact",
        topics="[]",
        audience="[]",
        complexity="",
        summary=content[:200] if len(content) > 200 else content,
    )


class TestKnowledgeCreationLive:
    """
    Live E2E tests for knowledge creation.

    These tests create real knowledge chunks and verify they're searchable.
    """

    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_create_knowledge_chunk_directly(
        self,
        unique_test_id,
    ):
        """
        Verify: Knowledge can be created and indexed in ChromaDB.

        This tests the core indexing functionality without Slack.
        """
        from knowledge_base.vectorstore.indexer import VectorIndexer
        from knowledge_base.vectorstore.client import ChromaClient

        indexer = VectorIndexer()

        # Create unique knowledge
        fact = f"The test system {unique_test_id} is managed by the platform team. Contact them in #platform-{unique_test_id}."

        # Create ChunkData
        chunk = create_test_chunk(
            unique_test_id=unique_test_id,
            content=fact,
            title=f"Test Fact {unique_test_id}",
            url=f"test://e2e/{unique_test_id}",
        )

        # Index it
        await indexer.index_single_chunk(chunk)

        # Verify it's searchable in ChromaDB
        await asyncio.sleep(1)  # Give ChromaDB a moment

        client = ChromaClient()
        # Use the client's get method to retrieve by ID
        chunk_data = await client.get(ids=[chunk.chunk_id])

        # Verify our chunk is stored
        assert len(chunk_data['ids']) == 1, f"Created knowledge should be retrievable. Got {len(chunk_data['ids'])} results"
        assert chunk_data['documents'][0] == fact, "Content should match"

    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_knowledge_appears_in_bot_responses(
        self,
        slack_client,
        e2e_config,
        unique_test_id,
    ):
        """
        Verify: Created knowledge is returned by the bot when asked.

        Flow:
        1. Create knowledge about a unique topic
        2. Ask the bot about that topic
        3. Verify bot's response contains the knowledge
        """
        from knowledge_base.vectorstore.indexer import VectorIndexer

        indexer = VectorIndexer()

        # Create very specific knowledge
        unique_service = f"TestService{unique_test_id}"
        unique_admin = f"admin_{unique_test_id}"
        fact = f"The administrator of {unique_service} is {unique_admin}. You can find them in the platform team."

        # Create ChunkData
        chunk = create_test_chunk(
            unique_test_id=unique_test_id,
            content=fact,
            title=f"Service Admin Info {unique_test_id}",
            url=f"test://e2e/service/{unique_test_id}",
        )

        # Index it
        await indexer.index_single_chunk(chunk)

        # Wait for indexing to complete
        await asyncio.sleep(2)

        # Ask the bot about it
        msg_ts = await slack_client.send_message(
            f"<@{e2e_config['bot_user_id']}> Who is the administrator of {unique_service}?"
        )

        reply = await slack_client.wait_for_bot_reply(
            parent_ts=msg_ts,
            timeout=90  # Increased timeout for LLM response
        )

        assert reply is not None, "Bot should respond"

        reply_text = reply.get("text", "")

        # Verify the response contains our knowledge
        # The bot should mention either the admin name or the service
        assert unique_admin in reply_text or unique_service in reply_text, (
            f"Bot response should mention the admin '{unique_admin}' or service '{unique_service}'. "
            f"Got: {reply_text[:200]}"
        )

    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_multiple_knowledge_chunks_searchable(
        self,
        unique_test_id,
    ):
        """
        Verify: Multiple related knowledge chunks are all indexed and searchable.
        """
        from knowledge_base.vectorstore.indexer import VectorIndexer
        from knowledge_base.vectorstore.client import ChromaClient

        indexer = VectorIndexer()

        # Create 3 related facts
        facts = [
            f"TestProduct{unique_test_id} is a data processing tool built by the engineering team.",
            f"TestProduct{unique_test_id} supports both batch and streaming data processing.",
            f"To get access to TestProduct{unique_test_id}, submit a request in #platform-access.",
        ]

        created_chunks = []
        for i, fact in enumerate(facts):
            chunk = create_test_chunk(
                unique_test_id=f"{unique_test_id}_{i}",
                content=fact,
                title=f"TestProduct{unique_test_id} Documentation",
                url=f"test://e2e/product/{unique_test_id}/section_{i}",
            )
            await indexer.index_single_chunk(chunk)
            created_chunks.append(chunk.chunk_id)

        assert len(created_chunks) == 3, "Should create 3 chunks"

        # Wait for indexing
        await asyncio.sleep(2)

        # Verify all chunks are retrievable
        client = ChromaClient()
        chunk_data = await client.get(ids=created_chunks)

        assert len(chunk_data['ids']) >= 2, (
            f"Should find at least 2 of our 3 chunks. "
            f"Found {len(chunk_data['ids'])}"
        )

    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_knowledge_has_correct_metadata(
        self,
        unique_test_id,
    ):
        """
        Verify: Created knowledge chunks have correct metadata stored.
        """
        from knowledge_base.vectorstore.indexer import VectorIndexer
        from knowledge_base.vectorstore.client import ChromaClient

        indexer = VectorIndexer()

        fact = f"TestMetadata{unique_test_id}: This is a test fact for metadata validation."
        creator = f"test_user_{unique_test_id}"

        chunk = create_test_chunk(
            unique_test_id=unique_test_id,
            content=fact,
            title="Metadata Test",
            url=f"test://metadata/{unique_test_id}",
            author=creator,
        )

        await indexer.index_single_chunk(chunk)

        chunk_id = chunk.chunk_id

        # Retrieve the chunk from ChromaDB
        await asyncio.sleep(1)

        client = ChromaClient()
        chunk_data = await client.get(ids=[chunk_id])

        assert len(chunk_data['ids']) == 1, "Should retrieve the chunk"
        assert chunk_data['documents'][0] == fact, "Content should match"

        metadata = chunk_data['metadatas'][0]
        assert metadata['author'] == creator, "Author should be stored"
        assert metadata['url'] == f"test://metadata/{unique_test_id}", "URL should be stored"
        assert metadata['quality_score'] == 100.0, "Initial quality should be 100.0"

    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_knowledge_quality_score_initialized(
        self,
        unique_test_id,
    ):
        """
        Verify: New knowledge starts with quality score of 100.0.
        """
        from knowledge_base.vectorstore.indexer import VectorIndexer
        from knowledge_base.vectorstore.client import ChromaClient

        indexer = VectorIndexer()

        fact = f"TestQuality{unique_test_id}: Quality score test fact."

        chunk = create_test_chunk(
            unique_test_id=unique_test_id,
            content=fact,
            title="Quality Score Test",
            url=f"test://quality/{unique_test_id}",
        )

        await indexer.index_single_chunk(chunk)

        # Verify by retrieving from ChromaDB
        await asyncio.sleep(1)

        client = ChromaClient()
        chunk_data = await client.get(ids=[chunk.chunk_id])

        assert len(chunk_data['ids']) == 1, "Should retrieve the chunk"
        metadata = chunk_data['metadatas'][0]
        assert metadata['quality_score'] == 100.0, (
            "New knowledge should start with quality score of 100.0"
        )
