"""
In-Memory Cache Implementation with Exact and Semantic In-Flight Deduplication.
Uses NumPy for fast vector similarity search and asyncio primitives for concurrency safety.
"""

import asyncio
from typing import Optional, List, Dict, Tuple
import numpy as np
from Service.interfaces.pipeline_context import MatchMethod
from Service.interfaces.base_cache import CacheResult, InFlightEntry


class InMemoryCache:
    """
    Implements CacheProvider protocol.
    Features:
    - O(1) exact hash table lookup.
    - Vectorized semantic search with cosine similarity >= threshold and exact edu_level match.
    - Concurrent in-flight deduplication (both exact and semantic) with fault isolation.
    """

    def __init__(self, threshold: float = 0.98, max_size: int = 50000):
        self._threshold = threshold
        self._max_size = max_size

        # Exact cache: cache_key -> CacheResult
        self._exact_cache: Dict[str, CacheResult] = {}

        # Semantic cache: list of vectors and metadata
        self._semantic_vectors: List[np.ndarray] = []
        self._semantic_entries: List[Dict] = []

        # In-flight entries: request_id -> InFlightEntry
        self._inflight_by_id: Dict[str, InFlightEntry] = {}
        # Mapping from exact cache_key -> leader request_id
        self._inflight_by_key: Dict[str, str] = {}
        self._lock = asyncio.Lock()

        # Telemetry stats
        self._stats = {
            "exact_hits": 0,
            "semantic_hits": 0,
            "exact_inflight_waits": 0,
            "semantic_inflight_waits": 0,
            "misses": 0,
            "stored": 0,
        }

    async def exact_lookup(self, cache_key: str) -> Optional[CacheResult]:
        """O(1) hash lookup."""
        result = self._exact_cache.get(cache_key)
        if result:
            self._stats["exact_hits"] += 1
            return result
        return None

    async def set_exact(self, cache_key: str, result: CacheResult) -> None:
        """Stores a result directly into the exact cache."""
        async with self._lock:
            self._exact_cache[cache_key] = result
            self._stats["stored"] += 1

    async def semantic_lookup(
        self,
        query_vector: List[float],
        edu_level: str,
        threshold: float = 0.98
    ) -> Optional[CacheResult]:
        """
        Cosine similarity search over stored vectors with identical edu_level requirement.
        """
        if not self._semantic_vectors or not query_vector:
            self._stats["misses"] += 1
            return None

        q_vec = np.array(query_vector, dtype=np.float32)
        q_norm = np.linalg.norm(q_vec)
        if q_norm < 1e-12:
            return None
        q_vec = q_vec / q_norm

        matrix = np.array(self._semantic_vectors, dtype=np.float32)
        sims = np.dot(matrix, q_vec)

        best_idx = int(np.argmax(sims))
        best_sim = float(sims[best_idx])

        if best_sim >= threshold:
            entry = self._semantic_entries[best_idx]
            # Strict education level match
            if entry["edu_level"] == edu_level:
                self._stats["semantic_hits"] += 1
                cached_res = entry["result"]
                return CacheResult(
                    code=cached_res.code,
                    name=cached_res.name,
                    confidence=best_sim,
                    matched_via=MatchMethod.SEMANTIC_CACHE,
                    section_name=cached_res.section_name,
                    subsection_name=cached_res.subsection_name,
                    division_name=cached_res.division_name,
                    group_name=cached_res.group_name,
                )

        self._stats["misses"] += 1
        return None

    async def check_or_register_inflight(
        self,
        request_id: str,
        cache_key: str,
        query_vector: List[float],
        norm_activity: str,
        edu_level: str,
        semantic_threshold: float = 0.98
    ) -> Tuple[bool, Optional[str]]:
        """
        Atomically checks if a matching leader is currently running.
        Strictly requires matching edu_level for both exact and semantic matches.
        """
        async with self._lock:
            # 1. Exact in-flight check
            if cache_key in self._inflight_by_key:
                leader_id = self._inflight_by_key[cache_key]
                if leader_id in self._inflight_by_id:
                    leader_entry = self._inflight_by_id[leader_id]
                    if leader_entry.education_level == edu_level:
                        leader_entry.waiters_count += 1
                        self._stats["exact_inflight_waits"] += 1
                        return True, leader_id

            # 2. Semantic in-flight check
            if query_vector and self._inflight_by_id:
                q_vec = np.array(query_vector, dtype=np.float32)
                q_norm = np.linalg.norm(q_vec)
                if q_norm > 1e-12:
                    q_vec = q_vec / q_norm

                    for leader_id, leader_entry in self._inflight_by_id.items():
                        if leader_entry.education_level == edu_level and leader_entry.query_vector:
                            l_vec = np.array(leader_entry.query_vector, dtype=np.float32)
                            l_norm = np.linalg.norm(l_vec)
                            if l_norm > 1e-12:
                                sim = float(np.dot(q_vec, l_vec / l_norm))
                                if sim >= semantic_threshold:
                                    leader_entry.waiters_count += 1
                                    self._stats["semantic_inflight_waits"] += 1
                                    return True, leader_id

            # 3. No match found: register this request as a new in-flight leader
            new_entry = InFlightEntry(
                request_id=request_id,
                cache_key=cache_key,
                query_vector=query_vector,
                education_level=edu_level,
                norm_activity=norm_activity,
            )
            self._inflight_by_id[request_id] = new_entry
            self._inflight_by_key[cache_key] = request_id
            return False, None

    async def wait_for_inflight(
        self,
        leader_request_id: str,
        timeout: float = 40.0
    ) -> Optional[CacheResult]:
        """
        Awaits completion of in-flight leader.
        Returns result on success, or None on failure/timeout (allowing graceful fallback).
        """
        async with self._lock:
            entry = self._inflight_by_id.get(leader_request_id)
            if not entry:
                return None
            event = entry.event

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            if entry.error or not entry.result:
                return None
            return entry.result
        except (asyncio.TimeoutError, Exception):
            return None

    async def complete_inflight(
        self,
        request_id: str,
        result: Optional[CacheResult],
        error: Optional[Exception] = None
    ) -> None:
        """
        Unblocks waiters and persists successful results in both exact and semantic caches.
        """
        async with self._lock:
            entry = self._inflight_by_id.get(request_id)
            if not entry:
                return

            entry.result = result
            entry.error = error
            entry.event.set()

            # Store in permanent caches if successful
            if result:
                self._exact_cache[entry.cache_key] = result
                if entry.query_vector:
                    v = np.array(entry.query_vector, dtype=np.float32)
                    norm = np.linalg.norm(v)
                    if norm > 1e-12:
                        self._semantic_vectors.append(v / norm)
                        self._semantic_entries.append({
                            "result": result,
                            "edu_level": entry.education_level,
                            "norm_activity": entry.norm_activity,
                        })
                self._stats["stored"] += 1

            # Cleanup in-flight maps
            self._inflight_by_id.pop(request_id, None)
            self._inflight_by_key.pop(entry.cache_key, None)

    def get_stats(self) -> Dict[str, int]:
        return dict(self._stats)
