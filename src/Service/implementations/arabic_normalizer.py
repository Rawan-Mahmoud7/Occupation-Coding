"""
Arabic Normalizer Implementation.
Cleans Arabic text, strips diacritics/tatweel, unifies letters, and creates deterministic cache keys.
"""

import re
import hashlib
from typing import Optional


class ArabicNormalizer:
    """Implements Normalizer protocol for Arabic occupation text processing."""

    # Diacritics regex (tashkeel + tatweel)
    TASHKEEL_RE = re.compile(r"[\u064B-\u065F\u0670\u0640]")
    # Non-word non-space symbols (punctuation, brackets, quotes, symbols) plus underscore
    NON_WORD_RE = re.compile(r"[^\w\s]|_", re.UNICODE)
    # Multiple whitespace reducer
    SPACES_RE = re.compile(r"\s+")

    def normalize_text(self, text: Optional[str]) -> str:
        """
        Cleans and standardizes Arabic text:
        - Strips tashkeel and tatweel.
        - Unifies alef: [أإآٱ] -> ا
        - Unifies alef maqsura: ى -> ي
        - Unifies taa marbouta: ة -> ه
        - Unifies hamzas: ؤ, ئ -> ء
        - Cleans symbols, punctuation, and multiple spaces.
        """
        if not text:
            return ""

        t = str(text)

        # 1. Remove diacritics and tatweel
        t = self.TASHKEEL_RE.sub("", t)

        # 2. Normalize letter forms
        t = re.sub(r"[أإآٱ]", "ا", t)
        t = t.replace("ى", "ي")
        t = t.replace("ة", "ه")
        t = re.sub(r"[ؤئ]", "ء", t)

        # 3. Clean symbols and non-letter noise
        t = self.NON_WORD_RE.sub(" ", t)

        # 4. Collapse spaces
        t = self.SPACES_RE.sub(" ", t).strip()

        return t

    def make_cache_key(self, norm_occ: str, norm_act: str, edu_level: str) -> str:
        """
        Builds a deterministic SHA-256 hash composite key.
        Format: hash(norm_occ|norm_act|edu_level)
        """
        occ = (norm_occ or "").strip()
        act = (norm_act or "").strip()
        edu = (edu_level or "").strip()
        composite = f"{occ}|{act}|{edu}"
        return hashlib.sha256(composite.encode("utf-8")).hexdigest()
