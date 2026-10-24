"""
Retriever Protocol.
Defines contracts for vector similarity search restricted to eligible ISCO sections.
"""

from typing import Protocol, List, Optional
from .pipeline_context import Candidate


class Retriever(Protocol):
    """Contract for restricted vector database search (e.g. pgvector)."""

    async def search(
        self,
        query_vector: List[float],
        eligible_sections: List[int],
        top_k: int = 20
    ) -> List[Candidate]:
        """
        Searches occupation vectors using Cosine similarity,
        strictly filtered to the provided eligible ISCO Major Sections (1 to 9).
        Returns candidates populated with code, name, and full hierarchy names.
        """
        ...

    async def get_by_code(self, code: str) -> Optional[Candidate]:
        """Retrieves an occupation and its full hierarchy names by its official code."""
        ...
