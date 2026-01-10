"""Metadata generation module."""

from knowledge_base.metadata.extractor import (
    MetadataExtractor,
    db_dict_to_metadata,
    metadata_to_db_dict,
)
from knowledge_base.metadata.normalizer import VocabularyNormalizer
from knowledge_base.metadata.schemas import DocumentMetadata

__all__ = [
    "MetadataExtractor",
    "VocabularyNormalizer",
    "DocumentMetadata",
    "metadata_to_db_dict",
    "db_dict_to_metadata",
]
