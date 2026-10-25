"""
Pipeline Context and Core Data Transfer Objects (DTOs).
Carries state and telemetry through every stage of the coding pipeline.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict


class MatchMethod(str, Enum):
    """How the final occupation code was determined."""
    EXACT_CACHE = "exact_cache"
    DB_EXACT_MATCH = "db_exact_match"
    SEMANTIC_CACHE = "semantic_cache"
    EXACT_INFLIGHT_WAIT = "exact_inflight_wait"
    SEMANTIC_INFLIGHT_WAIT = "semantic_inflight_wait"
    LLM_PIPELINE = "llm_pipeline"
    FALLBACK = "fallback"


@dataclass
class Candidate:
    """
    Candidate occupation retrieved from the vector index / database.
    Contains code, official name, similarity score, and complete hierarchy names.
    """
    code: str
    name: str
    similarity: float
    section_name: str = ""
    section_code: int = 0
    subsection_name: str = ""
    division_name: str = ""
    group_name: str = ""


@dataclass
class PipelineContext:
    """
    Central state container flowing through the 6 pipeline stages.
    Inputs are immutable; each stage populates its respective output fields.
    """

    # ── 1. Raw Input (Set once, immutable) ──
    row_index: int = -1
    raw_occupation: str = ""
    raw_activity: str = ""
    raw_education: str = ""
    raw_education_detail_a: str = ""
    raw_education_detail_b: str = ""

    # ── 2. Stage 1 Output (Normalization & Education Classification) ──
    norm_occupation: str = ""
    norm_activity: str = ""
    norm_education: str = ""
    education_level: str = ""                # EDU_1 | EDU_2A | EDU_2B | EDU_3 | EDU_4
    cache_key: str = ""

    # ── 3. Stage 2 Output (Fast Match Screening & Deduplication) ──
    matched_code: Optional[str] = None
    matched_name: Optional[str] = None
    matched_via: Optional[MatchMethod] = None
    confidence: float = 0.0
    is_resolved: bool = False
    waited_on_request_id: Optional[str] = None
    request_id: str = ""

    # ── 4. Stage 3 Output (LLM Understanding) ──
    work_description_formal: str = ""
    work_nature_sections: List[int] = field(default_factory=list)  # ISCO Sections (1 to 9)

    # ── 5. Stage 4 Output (Rule Gate) ──
    eligible_sections: List[int] = field(default_factory=list)     # Sections passing education gate

    # ── 6. Stage 5 Output (Embedding & Restricted Retrieval) ──
    query_embedding: Optional[List[float]] = None
    candidates: List[Candidate] = field(default_factory=list)

    # ── 7. Stage 6 Output (Final Selection) ──
    final_code: str = ""
    final_name: str = ""
    final_confidence: float = 0.0
    final_method: Optional[MatchMethod] = None
    selection_reasoning: str = ""

    # ── 8. Telemetry & Diagnostics ──
    processing_time_ms: float = 0.0
    stage_latencies: Dict[str, float] = field(default_factory=dict)
    error_message: Optional[str] = None
