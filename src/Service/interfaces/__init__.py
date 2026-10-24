"""
Service Interfaces Package.
Exports all protocols, data models, and enums for the occupation coding system.
"""

from .pipeline_context import MatchMethod, Candidate, PipelineContext
from .base_normalizer import Normalizer
from .base_classifier import EducationClassifier
from .base_rule_engine import RuleEngine
from .base_cache import CacheResult, InFlightEntry, CacheProvider
from .base_matcher import MatchResult, ExactMatcher
from .base_embedder import Embedder
from .base_llm import LLMUnderstandingResult, LLMClient
from .base_retriever import Retriever

__all__ = [
    "MatchMethod",
    "Candidate",
    "PipelineContext",
    "Normalizer",
    "EducationClassifier",
    "RuleEngine",
    "CacheResult",
    "InFlightEntry",
    "CacheProvider",
    "MatchResult",
    "ExactMatcher",
    "Embedder",
    "LLMUnderstandingResult",
    "LLMClient",
    "Retriever",
]
