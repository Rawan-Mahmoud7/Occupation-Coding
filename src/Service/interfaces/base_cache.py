"""
Cache Provider Protocol & In-Flight Deduplication Contracts.
Defines contracts for exact, semantic, and concurrent in-flight deduplication.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Protocol, Optional, List, Dict
from .pipeline_context import MatchMethod


@dataclass
class CacheResult:
    """Cached coding result returned upon cache hits."""
    code: str
    name: str
    confidence: float
    matched_via: MatchMethod = MatchMethod.EXACT_CACHE
    section_name: str = ""
    subsection_name: str = ""
    division_name: str = ""
    group_name: str = ""


@dataclass
class InFlightEntry:
    """Represents a request currently undergoing expensive LLM/retrieval processing."""
    request_id: str
    cache_key: str
    query_vector: List[float]
    education_level: str
    norm_activity: str
    event: asyncio.Event = field(default_factory=asyncio.Event)
    result: Optional[CacheResult] = None
    error: Optional[Exception] = None
    waiters_count: int = 0


class CacheProvider(Protocol):
    """Contract for multi-tier caching and concurrent in-flight deduplication."""

    async def exact_lookup(self, cache_key: str) -> Optional[CacheResult]:
        """O(1) lookup in completed exact cache."""
        ...

    async def set_exact(self, cache_key: str, result: CacheResult) -> None:
        """Stores a result directly into the exact cache."""
        ...

    async def semantic_lookup(
        self,
        query_vector: List[float],
        edu_level: str,
        threshold: float = 0.98
    ) -> Optional[CacheResult]:
        """Cosine similarity search against cached embeddings with education level filtering."""
        ...

    async def check_or_register_inflight(
        self,
        request_id: str,
        cache_key: str,
        query_vector: List[float],
        norm_activity: str,
        edu_level: str,
        semantic_threshold: float = 0.98
    ) -> tuple[bool, Optional[str]]:
        """
        Atomically checks if a matching request is currently in-flight (exact or semantic >= 98%).
        Returns:
            (True, leader_request_id) if a match is running and this request should wait.
            (False, None) if this request registered as the leader.
        """
        ...

    async def wait_for_inflight(
        self,
        leader_request_id: str,
        timeout: float = 40.0
    ) -> Optional[CacheResult]:
        """
        Awaits the completion of an in-flight leader request.
        Returns the result if successful, or None if the leader failed or timed out (allowing fallback).
        """
        ...

    async def complete_inflight(
        self,
        request_id: str,
        result: Optional[CacheResult],
        error: Optional[Exception] = None
    ) -> None:
        """
        Resolves an in-flight entry, awakens all waiting coroutines,
        and saves the result to both exact and semantic caches on success.
        """
        ...

    def get_stats(self) -> Dict[str, int]:
        """Returns cache telemetry: exact_hits, semantic_hits, exact_inflight_waits, semantic_inflight_waits."""
        ...
