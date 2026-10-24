"""
LLM Client Protocol.
Defines contracts for structured understanding, candidate selection, and account key rotation.
"""

from dataclasses import dataclass
from typing import Protocol, List, Tuple, Optional
from .pipeline_context import Candidate


@dataclass
class LLMUnderstandingResult:
    """Structured extraction produced by the LLM understanding stage."""
    work_description: str
    work_nature_sections: List[int]          # ISCO Major Sections (1 to 9)
    notes: Optional[str] = None


class LLMClient(Protocol):
    """Contract for interacting with LLM APIs with key rotation and structured prompts."""

    async def understand(self, row_context: str) -> LLMUnderstandingResult:
        """Extracts standardized work description and candidate ISCO Major Sections (1 to 9)."""
        ...

    async def select_best(
        self,
        row_context: str,
        candidates: List[Candidate]
    ) -> Tuple[str, str, float, str]:
        """
        Selects the most accurate occupation code from retrieved candidates.
        Returns: (assigned_code, assigned_name, confidence_score, selection_reasoning)
        """
        ...

    def rotate_key_on_exhaustion(self, current_key: str) -> str:
        """Switches to the next available account/key when monthly token quota or 429 occurs."""
        ...

    @property
    def concurrency_limit(self) -> int:
        """Maximum concurrent requests allowed for this client."""
        ...
