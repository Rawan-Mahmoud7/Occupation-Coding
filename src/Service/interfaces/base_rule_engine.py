"""
Rule Engine Protocol.
Defines contracts for enforcing education-to-section constraints and gating rules.
Operates on ISCO Major Groups / Sections (1 to 9).
"""

from typing import Protocol, Set, List


class RuleEngine(Protocol):
    """Contract for ISCO education-to-section compatibility and gating."""

    def get_eligible_sections(self, edu_level: str) -> Set[int]:
        """
        Returns the set of eligible ISCO Major Sections (1 to 9) for the given education level:
        - EDU_4: Sections {1, 2} primarily, plus specialized technical in {3}.
        - EDU_3: Sections {3, 4}.
        - EDU_2A / EDU_2B: Sections {4, 5, 6, 7, 8}.
        - EDU_1: Section {9} (Elementary occupations).
        """
        ...

    def apply_gate(self, edu_level: str, suggested_sections: List[int]) -> List[int]:
        """
        Intersects LLM-suggested sections with education-eligible sections.
        Applies fallback heuristics if intersection is empty.
        """
        ...

    def validate_code(self, code: str, edu_level: str) -> bool:
        """
        Validates whether a specific occupation code is permissible for the candidate's
        education level by checking its leading major section digit.
        """
        ...
