"""
ISCO Rule Engine Implementation.
Implements the core principle:
- Higher education qualifies for all equal and lower skill tiers.
- Lower education is strictly forbidden from higher professional tiers.
"""

from typing import Set, List


class ISCORuleEngine:
    """
    Implements RuleEngine protocol for ISCO Major Sections (1 to 9).
    """

    # Permitted sections per education tier
    ELIGIBLE_SECTIONS_MAP = {
        # Higher Education: Eligible for ALL sections (1 to 9)
        "EDU_4": {1, 2, 3, 4, 5, 6, 7, 8, 9},

        # Post-secondary: Eligible for all EXCEPT Section 2 (Professionals/Engineers/Doctors)
        "EDU_3": {1, 3, 4, 5, 6, 7, 8, 9},

        # General/Vocational Secondary, 3-year diploma: Sections 4, 5, 6, 7, 8, 9
        "EDU_2B": {4, 5, 6, 7, 8, 9},

        # Preparatory (إعدادي): Sections 5, 6, 7, 8, 9
        "EDU_2A": {5, 6, 7, 8, 9},

        # Illiterate / Primary / Read & Write: Elementary occupations only (Section 9)
        "EDU_1": {9},
    }

    def get_eligible_sections(self, edu_level: str) -> Set[int]:
        """Returns the set of eligible ISCO Major Sections (1 to 9) for this education level."""
        return self.ELIGIBLE_SECTIONS_MAP.get(edu_level, {1, 2, 3, 4, 5, 6, 7, 8, 9})

    def apply_gate(self, edu_level: str, suggested_sections: List[int]) -> List[int]:
        """
        Intersects LLM-suggested sections with education-eligible sections.
        If intersection exists, it is accepted.
        If conflict (e.g. preparatory claiming engineer/Section 2), strictly restricts to eligible sections.
        """
        eligible = self.get_eligible_sections(edu_level)
        intersection = [s for s in suggested_sections if s in eligible]

        if intersection:
            return sorted(intersection)

        # Conflict fallback: restrict strictly to the education ceiling
        return sorted(list(eligible))

    def validate_code(self, code: str, edu_level: str) -> bool:
        """
        Validates whether a specific occupation code complies with the candidate's
        education level by checking its leading major section digit (code[0]).
        """
        if not code:
            return False
        try:
            leading_digit = int(code[0])
            return leading_digit in self.get_eligible_sections(edu_level)
        except (ValueError, IndexError):
            return False
