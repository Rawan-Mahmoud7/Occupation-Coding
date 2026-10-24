"""
Education Classifier Protocol.
Defines contracts for mapping normalized education strings to standard ISCO-08 skill tiers.
"""

from typing import Protocol, Optional


class EducationClassifier(Protocol):
    """Contract for categorizing education descriptions into ISCO education levels."""

    def classify(
        self,
        norm_education: str,
        detail_a: Optional[str] = "",
        detail_b: Optional[str] = ""
    ) -> str:
        """
        Maps normalized education text to one of:
        - EDU_1: Illiterate, read & write, primary (Skill Level 1)
        - EDU_2A: Preparatory (Skill Level 2)
        - EDU_2B: General / Vocational Secondary, 3-year diploma (Skill Level 2)
        - EDU_3: Post-secondary institute, 5-year diploma (Skill Level 3)
        - EDU_4: Bachelor's, Master's, PhD, High qualifications (Skill Level 4)
        """
        ...

    def get_skill_level(self, edu_level: str) -> int:
        """Returns the corresponding ISCO skill level (1 to 4)."""
        ...
