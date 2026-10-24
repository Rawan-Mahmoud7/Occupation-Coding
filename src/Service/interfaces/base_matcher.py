"""
Exact Matcher Protocol.
Defines contracts for direct database lookups matching normalized occupation names.
"""

from dataclasses import dataclass
from typing import Protocol, Optional


@dataclass
class MatchResult:
    """Result of exact name matching in the occupation catalog."""
    code: str
    name: str
    section_code: int


class ExactMatcher(Protocol):
    """Contract for exact database name matching against official occupation dictionary."""

    async def match(self, normalized_name: str) -> Optional[MatchResult]:
        """
        Queries database for an exact name match.
        Returns MatchResult with code, name, and major section code to check education eligibility.
        """
        ...
