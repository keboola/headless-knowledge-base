"""Reciprocal Rank Fusion (RRF) for combining search results."""

from collections import defaultdict


def reciprocal_rank_fusion(
    *result_lists: list[tuple[str, float]],
    weights: tuple[float, ...] | None = None,
    k: int = 60,
) -> list[tuple[str, float]]:
    """Combine multiple ranked result lists using Reciprocal Rank Fusion.

    RRF is a simple and effective method for combining ranked lists.
    The score for each document is: sum(weight / (k + rank))

    Args:
        *result_lists: Variable number of result lists.
            Each list contains (doc_id, score) tuples sorted by relevance.
        weights: Optional weights for each result list.
            If None, all lists are weighted equally.
        k: Constant to prevent high scores for top-ranked documents.
            Default 60 is commonly used.

    Returns:
        Combined list of (doc_id, rrf_score) tuples, sorted by score descending.

    Example:
        >>> bm25_results = [("doc1", 5.0), ("doc2", 4.0), ("doc3", 3.0)]
        >>> vector_results = [("doc2", 0.9), ("doc1", 0.8), ("doc4", 0.7)]
        >>> combined = reciprocal_rank_fusion(
        ...     bm25_results,
        ...     vector_results,
        ...     weights=(0.3, 0.7)
        ... )
        >>> # doc2 appears high in both, so should be ranked first
    """
    if not result_lists:
        return []

    # Default to equal weights
    if weights is None:
        weights = tuple(1.0 for _ in result_lists)

    if len(weights) != len(result_lists):
        raise ValueError("Number of weights must match number of result lists")

    # Calculate RRF scores
    scores: dict[str, float] = defaultdict(float)

    for weight, results in zip(weights, result_lists):
        for rank, (doc_id, _original_score) in enumerate(results):
            # RRF formula: weight / (k + rank + 1)
            # rank is 0-indexed, so add 1 to make it 1-indexed
            scores[doc_id] += weight / (k + rank + 1)

    # Sort by RRF score descending
    sorted_results = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    return sorted_results


def normalize_scores(results: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Normalize scores to 0-1 range.

    Args:
        results: List of (doc_id, score) tuples

    Returns:
        List with normalized scores
    """
    if not results:
        return []

    scores = [score for _, score in results]
    min_score = min(scores)
    max_score = max(scores)

    if max_score == min_score:
        # All scores are equal
        return [(doc_id, 1.0) for doc_id, _ in results]

    normalized = [
        (doc_id, (score - min_score) / (max_score - min_score))
        for doc_id, score in results
    ]

    return normalized


def weighted_sum_fusion(
    *result_lists: list[tuple[str, float]],
    weights: tuple[float, ...] | None = None,
) -> list[tuple[str, float]]:
    """Combine results using weighted sum of normalized scores.

    Alternative to RRF that uses the actual scores.

    Args:
        *result_lists: Variable number of result lists with scores
        weights: Optional weights for each list

    Returns:
        Combined list sorted by weighted score
    """
    if not result_lists:
        return []

    if weights is None:
        weights = tuple(1.0 for _ in result_lists)

    # Normalize each list
    normalized_lists = [normalize_scores(results) for results in result_lists]

    # Combine scores
    scores: dict[str, float] = defaultdict(float)

    for weight, results in zip(weights, normalized_lists):
        for doc_id, score in results:
            scores[doc_id] += weight * score

    # Sort by combined score
    sorted_results = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    return sorted_results
