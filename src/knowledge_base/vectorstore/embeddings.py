"""Embeddings providers for vector indexing."""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Callable

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from knowledge_base.config import settings

logger = logging.getLogger(__name__)

# Provider registry
_EMBEDDING_REGISTRY: dict[str, Callable[[], "BaseEmbeddings"]] = {}


def register_embedding_provider(name: str):
    """Decorator to register an embedding provider factory."""

    def decorator(factory: Callable[[], "BaseEmbeddings"]):
        _EMBEDDING_REGISTRY[name.lower()] = factory
        return factory

    return decorator


class BaseEmbeddings(ABC):
    """Abstract base class for embedding providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider name."""
        pass

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Return the embedding dimension."""
        pass

    @abstractmethod
    async def embed(self, texts: list[str], **kwargs) -> list[list[float]]:
        """Generate embeddings for a list of texts.

        Args:
            texts: List of texts to embed
            **kwargs: Additional provider-specific parameters

        Returns:
            List of embedding vectors
        """
        pass

    async def embed_single(self, text: str) -> list[float]:
        """Generate embedding for a single text.

        Args:
            text: Text to embed

        Returns:
            Embedding vector
        """
        embeddings = await self.embed([text])
        return embeddings[0]


class SentenceTransformerEmbeddings(BaseEmbeddings):
    """Embeddings using sentence-transformers (runs locally, no external API)."""

    def __init__(self, model: str | None = None):
        """Initialize sentence-transformer embeddings.

        Args:
            model: Model name (defaults to settings.EMBEDDING_MODEL)
        """
        self.model_name = model or settings.EMBEDDING_MODEL
        self._model = None
        self._dimension: int | None = None

    @property
    def provider_name(self) -> str:
        return "sentence-transformer"

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            self._load_model()
        return self._dimension  # type: ignore

    def _load_model(self):
        """Lazy load the model."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer

                logger.info(f"Loading sentence-transformer model: {self.model_name}")
                self._model = SentenceTransformer(self.model_name)
                self._dimension = self._model.get_sentence_embedding_dimension()
                logger.info(f"Model loaded, dimension: {self._dimension}")
            except ImportError:
                raise ImportError(
                    "sentence-transformers not installed. "
                    "Install with: pip install sentence-transformers"
                )

    async def embed(self, texts: list[str], **kwargs) -> list[list[float]]:
        """Generate embeddings using sentence-transformers.

        Args:
            texts: List of texts to embed
            **kwargs: Additional parameters (ignored)

        Returns:
            List of embedding vectors
        """
        self._load_model()

        # sentence-transformers is synchronous, but fast for local inference
        embeddings = self._model.encode(texts, convert_to_numpy=True)
        return embeddings.tolist()


class OllamaEmbeddings(BaseEmbeddings):
    """Embeddings using Ollama (requires Ollama server)."""

    # Known dimensions for common Ollama embedding models
    MODEL_DIMENSIONS = {
        "mxbai-embed-large": 1024,
        "nomic-embed-text": 768,
        "all-minilm": 384,
    }

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 60.0,
    ):
        """Initialize Ollama embeddings.

        Args:
            base_url: Ollama server URL (defaults to settings.OLLAMA_BASE_URL)
            model: Model name (defaults to settings.OLLAMA_EMBEDDING_MODEL)
            timeout: Request timeout in seconds
        """
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.model = model or settings.OLLAMA_EMBEDDING_MODEL
        self.timeout = timeout
        self._dimension: int | None = self.MODEL_DIMENSIONS.get(self.model)

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            # Default to 1024 if unknown
            return 1024
        return self._dimension

    async def embed(self, texts: list[str], **kwargs) -> list[list[float]]:
        """Generate embeddings using Ollama.

        Args:
            texts: List of texts to embed
            **kwargs: Additional parameters (ignored)

        Returns:
            List of embedding vectors
        """
        embeddings = []

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                for text in texts:
                    response = await client.post(
                        f"{self.base_url}/api/embeddings",
                        json={"model": self.model, "prompt": text},
                    )
                    response.raise_for_status()
                    data = response.json()
                    embedding = data.get("embedding", [])
                    embeddings.append(embedding)

                    # Update dimension from first response
                    if self._dimension is None and embedding:
                        self._dimension = len(embedding)
        except httpx.HTTPError as e:
            logger.error(f"HTTP error while generating embeddings: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error while generating embeddings: {e}")
            raise

        return embeddings


class VertexAIEmbeddings(BaseEmbeddings):
    """Embeddings using Google Vertex AI Text Embeddings API."""

    TASK_TYPE_DOCUMENT = "RETRIEVAL_DOCUMENT"
    TASK_TYPE_QUERY = "RETRIEVAL_QUERY"

    def __init__(
        self,
        project: str | None = None,
        location: str | None = None,
        model: str | None = None,
    ):
        """Initialize Vertex AI embeddings.

        Args:
            project: GCP project ID (defaults to settings.VERTEX_AI_PROJECT or GCP_PROJECT_ID)
            location: GCP region (defaults to settings.VERTEX_AI_LOCATION)
            model: Model name (defaults to settings.VERTEX_AI_EMBEDDING_MODEL)
        """
        self.project = project or settings.VERTEX_AI_PROJECT or settings.GCP_PROJECT_ID
        self.location = location or settings.VERTEX_AI_LOCATION
        self.model_name = model or settings.VERTEX_AI_EMBEDDING_MODEL
        self._model = None
        self._initialized = False

        if not self.project:
            logger.warning("Vertex AI project not configured")

    @property
    def provider_name(self) -> str:
        return "vertex-ai"

    @property
    def dimension(self) -> int:
        return settings.VERTEX_AI_EMBEDDING_DIMENSION

    def _initialize(self):
        """Lazy initialization of Vertex AI client."""
        if self._initialized:
            return

        try:
            from google.cloud import aiplatform
            from vertexai.language_models import TextEmbeddingModel

            aiplatform.init(project=self.project, location=self.location)
            self._model = TextEmbeddingModel.from_pretrained(self.model_name)
            self._initialized = True
            logger.info(
                f"Initialized Vertex AI embeddings: model={self.model_name}, "
                f"project={self.project}, location={self.location}"
            )
        except ImportError as e:
            raise ImportError(
                "google-cloud-aiplatform not installed. "
                "Install with: pip install google-cloud-aiplatform"
            ) from e

    def _embed_batch(self, texts: list[str], task_type: str) -> list[list[float]]:
        """Synchronous batch embedding (runs in executor)."""
        from vertexai.language_models import TextEmbeddingInput

        inputs = [TextEmbeddingInput(text=text, task_type=task_type) for text in texts]
        embeddings = self._model.get_embeddings(inputs)
        return [e.values for e in embeddings]

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
    )
    async def embed(
        self, texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT"
    ) -> list[list[float]]:
        """Generate embeddings using Vertex AI.

        Args:
            texts: List of texts to embed
            task_type: Task type for embeddings (RETRIEVAL_DOCUMENT or RETRIEVAL_QUERY)

        Returns:
            List of embedding vectors
        """
        if not texts:
            return []

        self._initialize()
        all_embeddings = []
        batch_size = settings.VERTEX_AI_BATCH_SIZE

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            loop = asyncio.get_running_loop()
            embeddings = await loop.run_in_executor(
                None, lambda b=batch: self._embed_batch(b, task_type)
            )
            all_embeddings.extend(embeddings)

        return all_embeddings

    async def embed_single(self, text: str) -> list[float]:
        """Generate embedding for a single text (optimized for queries)."""
        embeddings = await self.embed([text], task_type=self.TASK_TYPE_QUERY)
        return embeddings[0]


# Register providers
@register_embedding_provider("sentence-transformer")
def _create_sentence_transformer():
    return SentenceTransformerEmbeddings()


@register_embedding_provider("ollama")
def _create_ollama():
    return OllamaEmbeddings()


@register_embedding_provider("vertex-ai")
def _create_vertex_ai():
    return VertexAIEmbeddings()


def get_available_embedding_providers() -> list[str]:
    """Get list of registered embedding provider names."""
    return list(_EMBEDDING_REGISTRY.keys())


def get_embeddings(provider: str | None = None) -> BaseEmbeddings:
    """Get an embeddings instance.

    Args:
        provider: Provider name (defaults to settings.EMBEDDING_PROVIDER)

    Returns:
        Embeddings instance

    Raises:
        ValueError: If provider is not registered
    """
    provider_name = (provider or settings.EMBEDDING_PROVIDER).lower()

    if provider_name not in _EMBEDDING_REGISTRY:
        available = ", ".join(get_available_embedding_providers())
        raise ValueError(
            f"Unknown embedding provider '{provider_name}'. Available: {available}"
        )

    return _EMBEDDING_REGISTRY[provider_name]()
