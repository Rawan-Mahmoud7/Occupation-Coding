"""
Normalizer Protocol.
Defines contracts for Arabic text normalization and deterministic cache key creation.
"""

from typing import Protocol, Optional


class Normalizer(Protocol):
    """Contract for text preprocessing and cache key generation."""

    def normalize_text(self, text: Optional[str]) -> str:
        """
        Cleans and standardizes Arabic text:
        - Unifies alef forms, yaa/alef maqsura, taa marbouta/haa.
        - Strips tashkeel (diacritics), tatweel (kashida), special punctuation, and digits.
        - Trims and collapses multiple whitespace characters.
        """
        ...

    def make_cache_key(self, norm_occ: str, norm_act: str, edu_level: str) -> str:
        """
        Generates a deterministic hash or composite string for exact cache lookup.
        """
        ...
