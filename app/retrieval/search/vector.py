"""Vector math operations for semantic similarity search."""

import math


def dot_product(a: list[float], b: list[float]) -> float:
    """Compute dot product of two vectors.

    Args:
        a: First vector
        b: Second vector

    Returns:
        Dot product value
    """
    return sum(x * y for x, y in zip(a, b, strict=False))


def vector_norm(a: list[float]) -> float:
    """Compute L2 norm of a vector.

    Args:
        a: Input vector

    Returns:
        L2 norm
    """
    return math.sqrt(sum(x * x for x in a))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors.

    Args:
        a: First embedding vector
        b: Second embedding vector

    Returns:
        Cosine similarity score in [-1, 1], or 0.0 for zero vectors
    """
    denominator = vector_norm(a) * vector_norm(b)
    if denominator == 0:
        return 0.0
    return dot_product(a, b) / denominator
