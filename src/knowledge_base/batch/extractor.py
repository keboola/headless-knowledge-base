"""Gemini Batch API integration for entity/relationship extraction.

Prepares JSONL requests (one per chunk), uploads to GCS, submits a batch
prediction job via the google-genai SDK, polls until completion, and
parses structured JSON results back into ChunkExtractionResult objects.

This replaces Graphiti's per-chunk 7-20 LLM calls with a single batch job
that processes all chunks in one pass.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

from google import genai
from google.cloud import storage as gcs
from google.genai.types import CreateBatchJobConfig, HttpOptions

from knowledge_base.batch.models import ChunkExtractionResult
from knowledge_base.config import Settings
from knowledge_base.vectorstore.indexer import ChunkData

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are an expert knowledge graph builder for a corporate knowledge base.\n"
    "Extract named entities and their factual relationships from the given text."
)

USER_PROMPT_TEMPLATE = """\
Extract entities and relationships from this text chunk.

Rules:
- Only extract clearly identifiable entities (people, teams, technologies, processes, concepts, organizations, locations)
- Use canonical/full entity names consistently
- Relationship facts must be directly supported by the text
- Each relationship must reference entities from your entity list

Text:
{content}

Source: {space_key} / {page_title}"""


class BatchExtractor:
    """Orchestrates Gemini Batch API extraction for document chunks.

    Workflow:
    1. ``prepare_jsonl`` -- build JSONL input and upload to GCS.
    2. ``submit_batch``  -- create a Gemini Batch API job.
    3. ``poll_until_complete`` -- wait for the job to finish.
    4. ``parse_results`` -- download output JSONL and deserialise.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

        # google-genai client for Batch API (Vertex AI mode)
        self._genai_client = genai.Client(
            http_options=HttpOptions(api_version="v1"),
            vertexai=True,
            project=settings.GCP_PROJECT_ID,
            location=settings.GCP_REGION,
        )

        # google-cloud-storage client for JSONL upload / download
        self._gcs_client = gcs.Client(project=settings.GCP_PROJECT_ID)

    # ------------------------------------------------------------------
    # 1. Prepare JSONL input
    # ------------------------------------------------------------------

    def prepare_jsonl(self, chunks: list[ChunkData]) -> str:
        """Build a JSONL file and upload it to GCS.

        Each line is a self-contained ``GenerateContentRequest`` keyed by
        ``chunk_id``.  Field names use REST-API camelCase, **not** Python
        SDK snake_case.

        Returns:
            The ``gs://`` URI of the uploaded JSONL file.
        """
        response_schema = ChunkExtractionResult.extraction_json_schema()
        lines: list[str] = []

        for chunk in chunks:
            user_text = USER_PROMPT_TEMPLATE.format(
                content=chunk.content,
                space_key=chunk.space_key,
                page_title=chunk.page_title,
            )

            # REST API (camelCase) payload -- NOT Python SDK snake_case
            request_line = {
                "key": chunk.chunk_id,
                "request": {
                    "contents": [
                        {
                            "role": "user",
                            "parts": [{"text": user_text}],
                        }
                    ],
                    "systemInstruction": {
                        "parts": [{"text": SYSTEM_PROMPT}],
                    },
                    "generationConfig": {
                        "temperature": 0.0,
                        "responseMimeType": "application/json",
                        "responseSchema": response_schema,
                    },
                },
            }
            lines.append(json.dumps(request_line, separators=(",", ":")))

        jsonl_body = "\n".join(lines)

        # Upload to GCS
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        blob_path = f"{self._settings.BATCH_GCS_PREFIX}/input_{timestamp}.jsonl"
        bucket = self._gcs_client.bucket(self._settings.BATCH_GCS_BUCKET)
        blob = bucket.blob(blob_path)
        blob.upload_from_string(jsonl_body, content_type="application/jsonl")

        gcs_uri = f"gs://{self._settings.BATCH_GCS_BUCKET}/{blob_path}"
        logger.info(
            "Uploaded JSONL with %d requests to %s (%d bytes)",
            len(lines),
            gcs_uri,
            len(jsonl_body),
        )
        return gcs_uri

    # ------------------------------------------------------------------
    # 2. Submit batch job
    # ------------------------------------------------------------------

    def submit_batch(self, input_uri: str) -> str:
        """Create a Gemini Batch API job from the uploaded JSONL.

        Args:
            input_uri: ``gs://`` URI of the input JSONL file.

        Returns:
            The batch job resource name (used for polling).
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output_uri = (
            f"gs://{self._settings.BATCH_GCS_BUCKET}"
            f"/{self._settings.BATCH_GCS_PREFIX}/output_{timestamp}/"
        )

        batch_job = self._genai_client.batches.create(
            model=self._settings.BATCH_GEMINI_MODEL,
            src=input_uri,
            config=CreateBatchJobConfig(dest=output_uri),
        )

        logger.info(
            "Submitted batch job %s (model=%s, input=%s, output=%s)",
            batch_job.name,
            self._settings.BATCH_GEMINI_MODEL,
            input_uri,
            output_uri,
        )
        return batch_job.name

    # ------------------------------------------------------------------
    # 3. Poll until complete
    # ------------------------------------------------------------------

    def poll_until_complete(self, job_name: str) -> str:
        """Block until the batch job reaches a terminal state.

        Args:
            job_name: Batch job resource name from ``submit_batch``.

        Returns:
            GCS URI of the output directory.

        Raises:
            RuntimeError: If the job fails, is cancelled, or polling times out.
        """
        terminal_states = {
            "JOB_STATE_SUCCEEDED",
            "JOB_STATE_FAILED",
            "JOB_STATE_CANCELLED",
        }

        poll_interval = self._settings.BATCH_POLL_INTERVAL
        max_duration = self._settings.BATCH_MAX_POLL_DURATION
        start = time.monotonic()
        prev_state: str | None = None

        while True:
            job = self._genai_client.batches.get(name=job_name)
            current_state = str(job.state) if job.state else "UNKNOWN"

            if current_state != prev_state:
                elapsed = time.monotonic() - start
                logger.info(
                    "Batch job %s state: %s (elapsed %.0fs)",
                    job_name,
                    current_state,
                    elapsed,
                )
                prev_state = current_state

            if current_state in terminal_states:
                break

            elapsed = time.monotonic() - start
            if elapsed >= max_duration:
                raise RuntimeError(
                    f"Batch job {job_name} timed out after {max_duration}s "
                    f"(last state: {current_state})"
                )

            time.sleep(poll_interval)

        # Handle terminal states
        if current_state == "JOB_STATE_FAILED":
            error_msg = str(job.error) if job.error else "unknown error"
            raise RuntimeError(f"Batch job {job_name} failed: {error_msg}")

        if current_state == "JOB_STATE_CANCELLED":
            raise RuntimeError(f"Batch job {job_name} was cancelled")

        # JOB_STATE_SUCCEEDED -- extract the output GCS URI
        output_uri = job.dest.gcs_uri if job.dest and job.dest.gcs_uri else None
        if not output_uri:
            raise RuntimeError(
                f"Batch job {job_name} succeeded but no output GCS URI found in response"
            )

        total_elapsed = time.monotonic() - start
        logger.info(
            "Batch job %s completed successfully in %.0fs (output: %s)",
            job_name,
            total_elapsed,
            output_uri,
        )
        return output_uri

    # ------------------------------------------------------------------
    # 4. Parse results
    # ------------------------------------------------------------------

    def parse_results(self, output_dir: str) -> dict[str, ChunkExtractionResult]:
        """Download and parse the output JSONL from GCS.

        Args:
            output_dir: ``gs://`` URI prefix where the batch job wrote
                        its output files.

        Returns:
            Mapping from ``chunk_id`` to ``ChunkExtractionResult``.
            Chunks that produced parsing errors are logged and skipped.
        """
        # Parse the GCS URI into bucket / prefix
        if not output_dir.startswith("gs://"):
            raise ValueError(f"Expected gs:// URI, got: {output_dir}")

        path = output_dir[len("gs://"):]
        bucket_name, _, prefix = path.partition("/")

        bucket = self._gcs_client.bucket(bucket_name)
        blobs = list(bucket.list_blobs(prefix=prefix))
        jsonl_blobs = [b for b in blobs if b.name.endswith(".jsonl")]

        if not jsonl_blobs:
            logger.warning("No JSONL output files found under %s", output_dir)
            return {}

        logger.info(
            "Downloading %d JSONL output file(s) from %s",
            len(jsonl_blobs),
            output_dir,
        )

        results: dict[str, ChunkExtractionResult] = {}
        total_lines = 0
        failed_lines = 0

        for blob in jsonl_blobs:
            content = blob.download_as_text(encoding="utf-8")
            for line_num, raw_line in enumerate(content.splitlines(), start=1):
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                total_lines += 1

                try:
                    row = json.loads(raw_line)
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "Skipping malformed JSON in %s line %d: %s",
                        blob.name,
                        line_num,
                        exc,
                    )
                    failed_lines += 1
                    continue

                try:
                    chunk_id = row["key"]
                    response_text = (
                        row["response"]["candidates"][0]["content"]["parts"][0]["text"]
                    )
                    extraction = ChunkExtractionResult.model_validate_json(response_text)
                    results[chunk_id] = extraction
                except (KeyError, IndexError, TypeError) as exc:
                    # Missing key / structure in the response row
                    chunk_id_hint = row.get("key", "<unknown>")
                    logger.warning(
                        "Skipping chunk %s -- response structure error: %s",
                        chunk_id_hint,
                        exc,
                    )
                    failed_lines += 1
                except Exception as exc:
                    # Pydantic validation or any other unexpected error
                    chunk_id_hint = row.get("key", "<unknown>")
                    logger.warning(
                        "Skipping chunk %s -- failed to parse extraction result: %s",
                        chunk_id_hint,
                        exc,
                    )
                    failed_lines += 1

        logger.info(
            "Parsed %d/%d results successfully (%d failures)",
            len(results),
            total_lines,
            failed_lines,
        )
        return results
