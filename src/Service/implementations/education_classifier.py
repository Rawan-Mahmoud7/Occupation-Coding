"""
Education Classifier Implementation.
Maps raw/normalized Egyptian education descriptions to standard ISCO tiers (EDU_1 to EDU_4).
Directly embeds the 27 real values from all_unique_values.xlsx and supports interactive timeout fallback.
"""

import os
import re
import json
import logging
from typing import Optional, Dict

log = logging.getLogger(__name__)


class ISCOEducationClassifier:
    """
    Implements EducationClassifier protocol.
    Contains verified mappings from all_unique_values.xlsx and persistent custom mappings.
    """

    # ── Normalized exact mappings for all 27 values in all_unique_values.xlsx ──
    EXACT_MAPPINGS: Dict[str, str] = {
        # EDU_1: Illiterate, primary, read & write, literacy, under 10 years, non-formal
        "يقرا ويكتب": "EDU_1",
        "يقرأ ويكتب": "EDU_1",
        "حاصل علي شهاده ابتدائيه": "EDU_1",
        "حاصل علي شهادة ابتدائية": "EDU_1",
        "ابتدائي": "EDU_1",
        "ابتدائيه": "EDU_1",
        "ابتدائية": "EDU_1",
        "امي": "EDU_1",
        "أمي": "EDU_1",
        "امى": "EDU_1",
        "أمى": "EDU_1",
        "حاصل علي شهاده محو الاميه": "EDU_1",
        "حاصل علي شهادة محو الامية": "EDU_1",
        "محو الاميه": "EDU_1",
        "محو الامية": "EDU_1",
        "اقل من 10 سنوات": "EDU_1",
        "أقل من 10 سنوات": "EDU_1",
        "حاصل علي شهاده تعليم غير نظامي": "EDU_1",
        "حاصل علي شهادة تعليم غير نظامي": "EDU_1",
        "تعليم غير نظامي": "EDU_1",
        "بدون مؤهل": "EDU_1",

        # EDU_2A: Preparatory (إعدادي)
        "اعدادي": "EDU_2A",
        "إعدادي": "EDU_2A",
        "حاصل علي شهاده اعداديه": "EDU_2A",
        "حاصل علي شهادة اعدادية": "EDU_2A",
        "اعداديه عامه": "EDU_2A",
        "اعدادية عامة": "EDU_2A",
        "اعداديه مهنيه": "EDU_2A",
        "اعدادية مهنية": "EDU_2A",
        "اعداديه ازهريه": "EDU_2A",
        "اعدادية ازهرية": "EDU_2A",

        # EDU_2B: General / Vocational Secondary, 3-year diploma, vocational training
        "ثانوي عام": "EDU_2B",
        "ثانويه عامه": "EDU_2B",
        "ثانوية عامة": "EDU_2B",
        "حاصل علي شهاده ثانوي عام / ازهري": "EDU_2B",
        "حاصل علي شهادة ثانوي عام / أزهري": "EDU_2B",
        "حاصل علي شهاده ثانهي عام / ازهري": "EDU_2B",   # Handling survey typo
        "حاصل علي شهادة ثانةي عام / أزهري": "EDU_2B",
        "حاصل علي شهاده ثانويه فنيه": "EDU_2B",
        "حاصل علي شهادة ثانوية فنية": "EDU_2B",
        "ثانوي فني": "EDU_2B",
        "ثانويه فنيه": "EDU_2B",
        "ثانوية فنية": "EDU_2B",
        "حاصل علي شهاده تدريب مهني / تلمذه صناعيه": "EDU_2B",
        "حاصل علي شهادة تدريب مهني / تلمذة صناعية": "EDU_2B",
        "حاصل علي شهاده تدريب مهني / تلمذه صناعيه-مدارس تكنولوجيا تطبيقيه": "EDU_2B",
        "حاصل علي شهادة تدريب مهني / تلمذة صناعية-مدارس تكنولوجيا تطبيقية": "EDU_2B",
        "تلمذه صناعيه": "EDU_2B",
        "تلمذة صناعية": "EDU_2B",
        "تدريب مهني": "EDU_2B",
        "دبلوم صنايع": "EDU_2B",
        "دبلوم تجاره": "EDU_2B",
        "دبلوم تجارة": "EDU_2B",
        "دبلوم زراعه": "EDU_2B",
        "دبلوم زراعة": "EDU_2B",
        "دبلوم فني": "EDU_2B",
        "دبلوم 3 سنوات": "EDU_2B",

        # EDU_3: Post-secondary institute, 5-year diploma
        "حاصل علي شهاده فوق المتوسط واقل من الجامعي": "EDU_3",
        "حاصل علي شهادة فوق المتوسط وأقل من الجامعي": "EDU_3",
        "فوق المتوسط واقل من الجامعي": "EDU_3",
        "فوق المتوسط وأقل من الجامعي": "EDU_3",
        "معهد فوق المتوسط": "EDU_3",
        "معهد فوق  المتوسط": "EDU_3",
        "فوق متوسط": "EDU_3",
        "معهد فني": "EDU_3",
        "معهد سنتين": "EDU_3",
        "دبلوم خمس سنوات": "EDU_3",
        "دبلوم 5 سنوات": "EDU_3",
        "معهد صحي": "EDU_3",
        "معهد تمريض فوق متوسط": "EDU_3",

        # EDU_4: High qualification, bachelor's, master's, PhD
        "شهاده جامعيه": "EDU_4",
        "شهادة جامعية": "EDU_4",
        "حاصل علي شهاده جامعيه": "EDU_4",
        "حاصل علي شهادة  جامعيه": "EDU_4",
        "حاصل علي شهادة جامعية": "EDU_4",
        "مؤهل جامعي": "EDU_4",
        "معهد عالي": "EDU_4",
        "فوق جامعي": "EDU_4",
        "شهاده اعلي من الجامعيه _دبلوم عالي /ماجستير/دكتوراه": "EDU_4",
        "شهادة اعلي من الجامعية _دبلوم عالي /ماجستير/دكتوراه": "EDU_4",
        "شهاده اعلي من الجامعيه (دبلوم عالي / ماجستير/ دكتوراه)": "EDU_4",
        "شهادة اعلي من الجامعية (دبلوم عالي / ماجستير/ دكتوراه)": "EDU_4",
        "بكالوريوس": "EDU_4",
        "ليسانس": "EDU_4",
        "ماجستير": "EDU_4",
        "دكتوراه": "EDU_4",
        "دراسات عليا": "EDU_4",
        "مؤهل عالي": "EDU_4",
    }

    def __init__(self, user_mappings_path: Optional[str] = None):
        self._user_mappings_path = user_mappings_path or os.path.join(
            os.path.dirname(__file__), "user_education_mappings.json"
        )
        self._user_mappings: Dict[str, str] = {}
        self._load_user_mappings()

    def _load_user_mappings(self) -> None:
        """Loads user-saved educational mappings if present."""
        if os.path.exists(self._user_mappings_path):
            try:
                with open(self._user_mappings_path, "r", encoding="utf-8") as f:
                    self._user_mappings = json.load(f)
            except Exception as e:
                log.warning(f"Could not load custom education mappings: {e}")

    def register_user_classification(self, raw_text: str, assigned_level: str) -> None:
        """Saves a user-confirmed classification into the persistent dictionary."""
        cleaned = raw_text.strip()
        self._user_mappings[cleaned] = assigned_level
        try:
            with open(self._user_mappings_path, "w", encoding="utf-8") as f:
                json.dump(self._user_mappings, f, ensure_ascii=False, indent=2)
            log.info(f"Registered user education mapping: '{cleaned}' -> {assigned_level}")
        except Exception as e:
            log.error(f"Failed to persist user education mapping: {e}")

    def _normalize_key(self, text: str) -> str:
        """Internal letter unifier for resilient mapping lookup."""
        if not text:
            return ""
        t = text.strip()
        t = re.sub(r"[أإآٱ]", "ا", t)
        t = t.replace("ى", "ي")
        t = t.replace("ة", "ه")
        t = re.sub(r"\s+", " ", t).strip()
        return t

    def classify(
        self,
        norm_education: str,
        detail_a: Optional[str] = "",
        detail_b: Optional[str] = ""
    ) -> str:
        """
        Classifies normalized education into EDU_1, EDU_2A, EDU_2B, EDU_3, EDU_4.
        If unknown, returns 'UNKNOWN' for user review/editing.
        """
        full_raw = f"{norm_education or ''} {detail_a or ''} {detail_b or ''}".strip()
        if not full_raw:
            return "UNKNOWN"

        # 1. Check direct raw keys
        if full_raw in self._user_mappings:
            return self._user_mappings[full_raw]
        if norm_education in self.EXACT_MAPPINGS:
            return self.EXACT_MAPPINGS[norm_education]

        # 2. Check normalized keys
        norm_key = self._normalize_key(norm_education)
        if norm_key in self.EXACT_MAPPINGS:
            return self.EXACT_MAPPINGS[norm_key]
        if norm_key in self._user_mappings:
            return self._user_mappings[norm_key]

        norm_full = self._normalize_key(full_raw)
        if norm_full in self.EXACT_MAPPINGS:
            return self.EXACT_MAPPINGS[norm_full]

        # 3. Keyword / Pattern checks in order of specificity
        # EDU_4 Check
        if any(w in norm_full for w in [
            "بكالوريوس", "ليسانس", "ماجستير", "دكتوراه", "جامعي", "جامعه", "كليه",
            "معهد عالي", "فوق جامعي", "دراسات عليا", "مؤهل عالي"
        ]):
            return "EDU_4"

        # EDU_3 Check
        if any(w in norm_full for w in [
            "فوق المتوسط", "فوق متوسط", "معهد فني", "معهد سنتين", "دبلوم خمس سنوات", "دبلوم 5 سنوات",
            "معهد صحي", "معهد تمريض"
        ]):
            return "EDU_3"

        # EDU_2B Check
        if any(w in norm_full for w in [
            "ثانوي عام", "ثانويه عامه", "ازهري", "ثانوي فني", "ثانويه فنيه",
            "تدريب مهني", "تلمذه صناعيه", "دبلوم صنايع", "دبلوم تجاره",
            "دبلوم زراعه", "دبلوم 3 سنوات", "تكنولوجيا تطبيقيه"
        ]):
            return "EDU_2B"

        # EDU_2A Check
        if any(w in norm_full for w in ["اعدادي", "اعداديه"]):
            return "EDU_2A"

        # EDU_1 Check
        if any(w in norm_full for w in [
            "امي", "يقرا ويكتب", "ابتدائي", "ابتدائيه",
            "محو اميه", "غير نظامي", "بدون مؤهل", "10 سنوات"
        ]):
            return "EDU_1"

        # 4. Unknown case (e.g. "حاصل علي تعليم اخري")
        return "UNKNOWN"

    def get_skill_level(self, edu_level: str) -> int:
        """Returns the corresponding ISCO skill level (1 to 4)."""
        mapping = {
            "EDU_1": 1,
            "EDU_2A": 2,
            "EDU_2B": 2,
            "EDU_3": 3,
            "EDU_4": 4,
        }
        return mapping.get(edu_level, 2)
