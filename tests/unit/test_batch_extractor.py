"""Tests for batch import pipeline extractor (Gemini Batch API integration)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from knowledge_base.batch.models import ChunkExtractionResult
from knowledge_base.vectorstore.indexer import ChunkData


def _make_chunk(
    chunk_id: str = "chunk-001",
    content: str = "Alice manages the Platform Team.",
    page_title: str = "Team Overview",
    space_key: str = "ENG",
) -> ChunkData:
    """Create a ChunkData instance for testing."""
    return ChunkData(
        chunk_id=chunk_id,
        content=content,
        page_id="page-1",
        page_title=page_title,
        chunk_index=0,
        space_key=space_key,
    )


def _make_settings(**overrides: object) -> MagicMock:
    """Create a mock Settings with batch-related defaults."""
    s = MagicMock()
    s.GCP_PROJECT_ID = "test-project"
    s.GCP_REGION = "us-central1"
    s.BATCH_GCS_BUCKET = "test-bucket"
    s.BATCH_GCS_PREFIX = "batch-import"
    s.BATCH_GEMINI_MODEL = "gemini-2.5-flash"
    s.BATCH_POLL_INTERVAL = 1
    s.BATCH_MAX_POLL_DURATION = 10
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


# ---------------------------------------------------------------------------
# JSONL line format tests
# ---------------------------------------------------------------------------


class TestPrepareJsonl:
    """Tests for BatchExtractor.prepare_jsonl -- JSONL line structure."""

    @patch("knowledge_base.batch.extractor.gcs")
    @patch("knowledge_base.batch.extractor.genai")
    def test_jsonl_line_has_camel_case_fields(
        self, mock_genai: MagicMock, mock_gcs: MagicMock
    ) -> None:
        """JSONL lines must use REST-API camelCase field names."""
        from knowledge_base.batch.extractor import BatchExtractor

        mock_blob = MagicMock()
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        mock_gcs.Client.return_value.bucket.return_value = mock_bucket

        settings = _make_settings()
        extractor = BatchExtractor(settings)
        chunk = _make_chunk()

        extractor.prepare_jsonl([chunk])

        # Capture what was uploaded
        uploaded_body = mock_blob.upload_from_string.call_args[0][0]
        line = json.loads(uploaded_body.split("\n")[0])
        request = line["request"]

        # camelCase fields -- NOT snake_case
        assert "systemInstruction" in request
        assert "generationConfig" in request
        assert "responseMimeType" in request["generationConfig"]
        assert "responseSchema" in request["generationConfig"]

        # Ensure snake_case variants are NOT present
        assert "system_instruction" not in request
        assert "generation_config" not in request

    @patch("knowledge_base.batch.extractor.gcs")
    @patch("knowledge_base.batch.extractor.genai")
    def test_chunk_id_is_key_field(
        self, mock_genai: MagicMock, mock_gcs: MagicMock
    ) -> None:
        """Each JSONL line uses chunk_id as the 'key' field."""
        from knowledge_base.batch.extractor import BatchExtractor

        mock_blob = MagicMock()
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        mock_gcs.Client.return_value.bucket.return_value = mock_bucket

        settings = _make_settings()
        extractor = BatchExtractor(settings)
        chunk = _make_chunk(chunk_id="my-chunk-42")

        extractor.prepare_jsonl([chunk])

        uploaded_body = mock_blob.upload_from_string.call_args[0][0]
        line = json.loads(uploaded_body.split("\n")[0])
        assert line["key"] == "my-chunk-42"

    @patch("knowledge_base.batch.extractor.gcs")
    @patch("knowledge_base.batch.extractor.genai")
    def test_prompt_includes_chunk_content_and_metadata(
        self, mock_genai: MagicMock, mock_gcs: MagicMock
    ) -> None:
        """The user prompt must include content, page_title, and space_key."""
        from knowledge_base.batch.extractor import BatchExtractor

        mock_blob = MagicMock()
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        mock_gcs.Client.return_value.bucket.return_value = mock_bucket

        settings = _make_settings()
        extractor = BatchExtractor(settings)
        chunk = _make_chunk(
            content="Kubernetes deployment guide",
            page_title="K8s Guide",
            space_key="INFRA",
        )

        extractor.prepare_jsonl([chunk])

        uploaded_body = mock_blob.upload_from_string.call_args[0][0]
        line = json.loads(uploaded_body.split("\n")[0])

        user_text = line["request"]["contents"][0]["parts"][0]["text"]
        assert "Kubernetes deployment guide" in user_text
        assert "K8s Guide" in user_text
        assert "INFRA" in user_text

    @patch("knowledge_base.batch.extractor.gcs")
    @patch("knowledge_base.batch.extractor.genai")
    def test_multiple_chunks_produce_multiple_lines(
        self, mock_genai: MagicMock, mock_gcs: MagicMock
    ) -> None:
        """Each chunk produces one JSONL line."""
        from knowledge_base.batch.extractor import BatchExtractor

        mock_blob = MagicMock()
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        mock_gcs.Client.return_value.bucket.return_value = mock_bucket

        settings = _make_settings()
        extractor = BatchExtractor(settings)

        chunks = [
            _make_chunk(chunk_id=f"chunk-{i}", content=f"Content {i}")
            for i in range(3)
        ]
        extractor.prepare_jsonl(chunks)

        uploaded_body = mock_blob.upload_from_string.call_args[0][0]
        lines = [ln for ln in uploaded_body.split("\n") if ln.strip()]
        assert len(lines) == 3

        # Verify each line has distinct key
        keys = {json.loads(ln)["key"] for ln in lines}
        assert keys == {"chunk-0", "chunk-1", "chunk-2"}

    @patch("knowledge_base.batch.extractor.gcs")
    @patch("knowledge_base.batch.extractor.genai")
    def test_response_schema_included_in_generation_config(
        self, mock_genai: MagicMock, mock_gcs: MagicMock
    ) -> None:
        """responseSchema in generationConfig matches extraction_json_schema()."""
        from knowledge_base.batch.extractor import BatchExtractor

        mock_blob = MagicMock()
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        mock_gcs.Client.return_value.bucket.return_value = mock_bucket

        settings = _make_settings()
        extractor = BatchExtractor(settings)
        chunk = _make_chunk()

        extractor.prepare_jsonl([chunk])

        uploaded_body = mock_blob.upload_from_string.call_args[0][0]
        line = json.loads(uploaded_body.split("\n")[0])
        schema_in_line = line["request"]["generationConfig"]["responseSchema"]

        expected_schema = ChunkExtractionResult.extraction_json_schema()
        assert schema_in_line == expected_schema

    @patch("knowledge_base.batch.extractor.gcs")
    @patch("knowledge_base.batch.extractor.genai")
    def test_gcs_uri_returned(
        self, mock_genai: MagicMock, mock_gcs: MagicMock
    ) -> None:
        """prepare_jsonl returns a gs:// URI."""
        from knowledge_base.batch.extractor import BatchExtractor

        mock_blob = MagicMock()
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        mock_gcs.Client.return_value.bucket.return_value = mock_bucket

        settings = _make_settings()
        extractor = BatchExtractor(settings)
        chunk = _make_chunk()

        result = extractor.prepare_jsonl([chunk])
        assert result.startswith("gs://test-bucket/batch-import/")
        assert result.endswith(".jsonl")

    @patch("knowledge_base.batch.extractor.gcs")
    @patch("knowledge_base.batch.extractor.genai")
    def test_system_instruction_present(
        self, mock_genai: MagicMock, mock_gcs: MagicMock
    ) -> None:
        """Each line carries a system instruction."""
        from knowledge_base.batch.extractor import BatchExtractor

        mock_blob = MagicMock()
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        mock_gcs.Client.return_value.bucket.return_value = mock_bucket

        settings = _make_settings()
        extractor = BatchExtractor(settings)
        chunk = _make_chunk()

        extractor.prepare_jsonl([chunk])

        uploaded_body = mock_blob.upload_from_string.call_args[0][0]
        line = json.loads(uploaded_body.split("\n")[0])
        sys_text = line["request"]["systemInstruction"]["parts"][0]["text"]
        assert "knowledge graph" in sys_text.lower()


# ---------------------------------------------------------------------------
# parse_results tests
# ---------------------------------------------------------------------------


class TestParseResults:
    """Tests for BatchExtractor.parse_results."""

    @patch("knowledge_base.batch.extractor.gcs")
    @patch("knowledge_base.batch.extractor.genai")
    def test_parse_successful_response(
        self, mock_genai: MagicMock, mock_gcs: MagicMock
    ) -> None:
        """Successful JSONL rows are parsed into ChunkExtractionResult."""
        from knowledge_base.batch.extractor import BatchExtractor

        extraction_json = json.dumps({
            "entities": [
                {"name": "Alice", "entity_type": "Person", "summary": "An engineer."}
            ],
            "relationships": [],
            "summary": "About Alice.",
        })

        output_line = json.dumps({
            "key": "chunk-001",
            "response": {
                "candidates": [
                    {"content": {"parts": [{"text": extraction_json}]}}
                ]
            },
        })

        mock_blob = MagicMock()
        mock_blob.name = "output/output_001.jsonl"
        mock_blob.download_as_text.return_value = output_line

        mock_bucket = MagicMock()
        mock_bucket.list_blobs.return_value = [mock_blob]
        mock_gcs.Client.return_value.bucket.return_value = mock_bucket

        settings = _make_settings()
        extractor = BatchExtractor(settings)

        results = extractor.parse_results("gs://test-bucket/output/")

        assert "chunk-001" in results
        result = results["chunk-001"]
        assert isinstance(result, ChunkExtractionResult)
        assert len(result.entities) == 1
        assert result.entities[0].name == "Alice"
        assert result.summary == "About Alice."

    @patch("knowledge_base.batch.extractor.gcs")
    @patch("knowledge_base.batch.extractor.genai")
    def test_parse_failed_response_is_skipped(
        self, mock_genai: MagicMock, mock_gcs: MagicMock
    ) -> None:
        """Lines with missing response structure are logged and skipped."""
        from knowledge_base.batch.extractor import BatchExtractor

        # Missing "candidates" key
        output_line = json.dumps({
            "key": "chunk-bad",
            "response": {"error": "model overloaded"},
        })

        mock_blob = MagicMock()
        mock_blob.name = "output/output_001.jsonl"
        mock_blob.download_as_text.return_value = output_line

        mock_bucket = MagicMock()
        mock_bucket.list_blobs.return_value = [mock_blob]
        mock_gcs.Client.return_value.bucket.return_value = mock_bucket

        settings = _make_settings()
        extractor = BatchExtractor(settings)

        results = extractor.parse_results("gs://test-bucket/output/")
        assert len(results) == 0

    @patch("knowledge_base.batch.extractor.gcs")
    @patch("knowledge_base.batch.extractor.genai")
    def test_parse_malformed_json_is_skipped(
        self, mock_genai: MagicMock, mock_gcs: MagicMock
    ) -> None:
        """Lines with invalid JSON are logged and skipped."""
        from knowledge_base.batch.extractor import BatchExtractor

        mock_blob = MagicMock()
        mock_blob.name = "output/output_001.jsonl"
        mock_blob.download_as_text.return_value = "not valid json{{"

        mock_bucket = MagicMock()
        mock_bucket.list_blobs.return_value = [mock_blob]
        mock_gcs.Client.return_value.bucket.return_value = mock_bucket

        settings = _make_settings()
        extractor = BatchExtractor(settings)

        results = extractor.parse_results("gs://test-bucket/output/")
        assert len(results) == 0

    @patch("knowledge_base.batch.extractor.gcs")
    @patch("knowledge_base.batch.extractor.genai")
    def test_parse_empty_output_returns_empty(
        self, mock_genai: MagicMock, mock_gcs: MagicMock
    ) -> None:
        """No output files returns empty dict."""
        from knowledge_base.batch.extractor import BatchExtractor

        mock_bucket = MagicMock()
        mock_bucket.list_blobs.return_value = []
        mock_gcs.Client.return_value.bucket.return_value = mock_bucket

        settings = _make_settings()
        extractor = BatchExtractor(settings)

        results = extractor.parse_results("gs://test-bucket/output/")
        assert results == {}

    @patch("knowledge_base.batch.extractor.gcs")
    @patch("knowledge_base.batch.extractor.genai")
    def test_parse_mixed_good_and_bad_rows(
        self, mock_genai: MagicMock, mock_gcs: MagicMock
    ) -> None:
        """Good rows are returned, bad rows are skipped."""
        from knowledge_base.batch.extractor import BatchExtractor

        good_extraction = json.dumps({
            "entities": [],
            "relationships": [],
            "summary": "Good summary.",
        })
        good_line = json.dumps({
            "key": "chunk-good",
            "response": {
                "candidates": [
                    {"content": {"parts": [{"text": good_extraction}]}}
                ]
            },
        })
        bad_line = json.dumps({
            "key": "chunk-bad",
            "response": {"error": "failed"},
        })

        mock_blob = MagicMock()
        mock_blob.name = "output/output_001.jsonl"
        mock_blob.download_as_text.return_value = f"{good_line}\n{bad_line}"

        mock_bucket = MagicMock()
        mock_bucket.list_blobs.return_value = [mock_blob]
        mock_gcs.Client.return_value.bucket.return_value = mock_bucket

        settings = _make_settings()
        extractor = BatchExtractor(settings)

        results = extractor.parse_results("gs://test-bucket/output/")
        assert len(results) == 1
        assert "chunk-good" in results

    @patch("knowledge_base.batch.extractor.gcs")
    @patch("knowledge_base.batch.extractor.genai")
    def test_parse_invalid_gcs_uri_raises(
        self, mock_genai: MagicMock, mock_gcs: MagicMock
    ) -> None:
        """Non-gs:// URI raises ValueError."""
        from knowledge_base.batch.extractor import BatchExtractor

        settings = _make_settings()
        extractor = BatchExtractor(settings)

        with pytest.raises(ValueError, match="Expected gs:// URI"):
            extractor.parse_results("https://example.com/output/")

    @patch("knowledge_base.batch.extractor.gcs")
    @patch("knowledge_base.batch.extractor.genai")
    def test_parse_blank_lines_are_ignored(
        self, mock_genai: MagicMock, mock_gcs: MagicMock
    ) -> None:
        """Blank lines in JSONL output are silently ignored."""
        from knowledge_base.batch.extractor import BatchExtractor

        extraction = json.dumps({
            "entities": [],
            "relationships": [],
            "summary": "Test.",
        })
        good_line = json.dumps({
            "key": "chunk-1",
            "response": {
                "candidates": [
                    {"content": {"parts": [{"text": extraction}]}}
                ]
            },
        })

        mock_blob = MagicMock()
        mock_blob.name = "output/output_001.jsonl"
        mock_blob.download_as_text.return_value = f"\n{good_line}\n\n\n"

        mock_bucket = MagicMock()
        mock_bucket.list_blobs.return_value = [mock_blob]
        mock_gcs.Client.return_value.bucket.return_value = mock_bucket

        settings = _make_settings()
        extractor = BatchExtractor(settings)

        results = extractor.parse_results("gs://test-bucket/output/")
        assert len(results) == 1
