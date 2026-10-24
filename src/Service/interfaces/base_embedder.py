"""
Embedder Protocol.
Shared text embedding service for semantic cache and vector retrieval.
"""

from typing import Protocol, List


class Embedder(Protocol):
    """Contract for dense vector embedding generation."""

    async def embed(self, text: str) -> List[float]:
        """Converts a single text into a dense vector (respecting RPM/TPM rate limits)."""
        ...

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Batched vector generation to optimize throughput and rate limit allocations."""
        ...

    @property
    def dimension(self) -> int:
        """Dimension size of the embedding vectors (e.g. 1024 for voyage-context-4)."""
        ...
