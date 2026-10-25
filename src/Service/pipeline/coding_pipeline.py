"""
Coding Pipeline Orchestrator.
Coordinates the 6-stage Egyptian Standard Occupation Coding System using asyncio queues and concurrent workers.
Enforces strict ISCO education eligibility rules at every stage:
- Higher education qualifies for equal and lower tiers.
- Lower education is strictly forbidden from higher professional tiers (e.g. Section 2 forbidden for secondary/EDU_2B).
"""

import asyncio
import logging
import time
from typing import List, Tuple, Dict, Optional

from config import Settings
from api.schemas import OccupationRowInput, SingleCodingResult, BatchSummaryMetrics
from Service.interfaces.pipeline_context import PipelineContext, MatchMethod
from Service.interfaces.base_cache import CacheResult
from Service.pipeline.service_registry import ServiceRegistry

log = logging.getLogger(__name__)

# ── Stage label constants (used in trace logs) ──────────────────────────────
_S1 = "STAGE-1 [Normalization+Edu]"
_S2 = "STAGE-2 [FastMatch+Dedup]"
_S3 = "STAGE-3 [LLM-Understand]"
_S4 = "STAGE-4 [Rule-Gate]"
_S5 = "STAGE-5 [VectorRetrieval]"
_S6 = "STAGE-6 [LLM-Select]"


def _ms(t0: float) -> str:
    """Returns elapsed milliseconds since t0 as a formatted string."""
    return f"{(time.monotonic() - t0) * 1000:.2f}ms"


class CodingPipeline:
    """
    Coordinates the 6 stages using asyncio queues and concurrent workers:
    Stage 1: Arabic Normalization & Education Classification (Synchronous CPU)
    Stage 2: Fast Match Screening & In-Flight Deduplication (Exact Cache -> DB Match -> Voyage Vector -> Semantic Cache -> In-Flight Wait)
    Stage 3: LLM Understanding (Extract work description & candidate Sections 1-9)
    Stage 4: Rule Gate (Education ceiling applied on candidate sections)
    Stage 5: Restricted Vector Retrieval (pgvector filtered by eligible sections)
    Stage 6: Final LLM Selection (Names only, code assigned & validated in Python)
    """

    def __init__(self, registry: ServiceRegistry, settings: Settings):
        self._reg = registry
        self._settings = settings

    def add_llm_api_key(self, new_key: str) -> int:
        """Dynamically adds an API key to the active LLM client rotator."""
        if hasattr(self._reg.llm, "add_api_key_and_resume"):
            self._reg.llm.add_api_key_and_resume(new_key)
            if hasattr(self._reg.llm, "_api_keys"):
                return len(self._reg.llm._api_keys)
        return 1

    async def process_batch(
        self,
        rows: List[OccupationRowInput],
        bypass_cache: bool = False,
    ) -> Tuple[List[SingleCodingResult], BatchSummaryMetrics]:
        """
        Processes a batch of rows concurrently using pipelined queues.
        Returns ordered results matching original row indexes and summary metrics.
        """
        start_time = time.monotonic()
        results: Dict[int, SingleCodingResult] = {}

        if not rows:
            metrics = BatchSummaryMetrics(
                total_rows=0,
                total_duration_ms=0.0,
                average_row_time_ms=0.0,
            )
            return [], metrics

        # ── Stage 1: CPU Normalization & Classification ──
        contexts: List[PipelineContext] = []
        for i, r in enumerate(rows):
            t_s1 = time.monotonic()
            log.debug(
                f"[ROW #{i}] ▶ {_S1} | IN: occupation=%r  activity=%r  education_raw=%r",
                r.occupation_name, r.activity, r.education_raw,
            )
            ctx = PipelineContext(
                row_index=i,
                request_id=f"row_{i}_{time.time()}",
                raw_occupation=r.occupation_name or "",
                raw_activity=r.activity or "",
                raw_education=r.education_raw or "",
                raw_education_detail_a=r.education_detail_a or "",
                raw_education_detail_b=r.education_detail_b or "",
            )
            ctx.norm_occupation = self._reg.normalizer.normalize_text(ctx.raw_occupation)
            ctx.norm_activity   = self._reg.normalizer.normalize_text(ctx.raw_activity)
            ctx.norm_education  = self._reg.normalizer.normalize_text(ctx.raw_education)
            ctx.education_level = self._reg.classifier.classify(
                ctx.norm_education, ctx.raw_education_detail_a, ctx.raw_education_detail_b
            )
            ctx.cache_key = self._reg.normalizer.make_cache_key(
                ctx.norm_occupation, ctx.norm_activity, ctx.education_level
            )
            ctx.eligible_sections = sorted(list(self._reg.rule_engine.get_eligible_sections(ctx.education_level)))
            elapsed_s1 = (time.monotonic() - t_s1) * 1000
            ctx.stage_latencies[_S1] = elapsed_s1
            log.debug(
                f"[ROW #{i}] ✓ {_S1} | OUT: norm_occ=%r  norm_act=%r  edu_level=%s  "
                f"eligible_sections=%s  cache_key=%s | %.2fms",
                ctx.norm_occupation, ctx.norm_activity, ctx.education_level,
                ctx.eligible_sections, ctx.cache_key, elapsed_s1,
            )
            contexts.append(ctx)

        # ── Queues for Pipelined Concurrent Stages ──
        raw_queue:       asyncio.Queue[PipelineContext] = asyncio.Queue()
        llm_queue:       asyncio.Queue[PipelineContext] = asyncio.Queue()
        retrieval_queue: asyncio.Queue[PipelineContext] = asyncio.Queue()
        select_queue:    asyncio.Queue[PipelineContext] = asyncio.Queue()

        for ctx in contexts:
            await raw_queue.put(ctx)

        # ── Worker Counts ──
        dispatcher_count = 4
        llm_concurrency  = max(1, self._settings.LLM_CONCURRENCY)
        retrieval_count  = 8

        workers = [
            *[asyncio.create_task(self._dispatcher_worker(raw_queue, llm_queue, results, bypass_cache)) for _ in range(dispatcher_count)],
            *[asyncio.create_task(self._understand_worker(llm_queue, retrieval_queue, results)) for _ in range(llm_concurrency)],
            *[asyncio.create_task(self._retrieval_worker(retrieval_queue, select_queue, results)) for _ in range(retrieval_count)],
            *[asyncio.create_task(self._select_worker(select_queue, results)) for _ in range(llm_concurrency)],
        ]

        # Wait for all stages to process their queues
        await raw_queue.join()
        await llm_queue.join()
        await retrieval_queue.join()
        await select_queue.join()

        # Stop workers cleanly
        for w in workers:
            w.cancel()

        # Ensure all contexts have a result
        for ctx in contexts:
            if ctx.row_index not in results:
                results[ctx.row_index] = self._build_result(ctx, start_time)

        ordered_results = [results[i] for i in range(len(rows))]
        duration_ms = (time.monotonic() - start_time) * 1000.0
        metrics = self._compute_metrics(ordered_results, duration_ms)
        return ordered_results, metrics

    # ─────────────────────────────────────────────────────────────────────────
    # Stage 2 Worker: Fast Match Screening + Deduplication
    # ─────────────────────────────────────────────────────────────────────────
    async def _dispatcher_worker(
        self,
        raw_queue: asyncio.Queue,
        llm_queue: asyncio.Queue,
        results: Dict[int, SingleCodingResult],
        bypass_cache: bool,
    ) -> None:
        """
        Stage 2 Worker:
        Checks Exact Cache, DB Exact Match, Computes Voyage Embedding (ONCE),
        Checks Semantic Cache, Handles In-Flight Deduplication.
        Strictly enforces education eligibility on any cached or DB hit.
        """
        while True:
            ctx: PipelineContext = await raw_queue.get()
            t0 = time.monotonic()
            i  = ctx.row_index
            try:
                log.debug(
                    f"[ROW #{i}] ▶ {_S2} | IN: cache_key=%s  edu_level=%s  bypass_cache=%s",
                    ctx.cache_key, ctx.education_level, bypass_cache,
                )

                if not bypass_cache:
                    # ── 2.1  Exact Cache O(1) ──────────────────────────────
                    t_sub = time.monotonic()
                    cached = await self._reg.cache.exact_lookup(ctx.cache_key)
                    if cached and self._reg.rule_engine.validate_code(cached.code, ctx.education_level):
                        lat = (time.monotonic() - t_sub) * 1000
                        ctx.stage_latencies[_S2] = lat
                        ctx.matched_code = cached.code
                        ctx.matched_name = cached.name
                        ctx.matched_via  = MatchMethod.EXACT_CACHE
                        ctx.confidence   = cached.confidence if cached.confidence > 0 else 1.0
                        ctx.is_resolved  = True
                        log.debug(
                            f"[ROW #{i}] ✓ {_S2} | HIT: exact_cache  code=%s  name=%r  conf=%.4f | %.2fms",
                            cached.code, cached.name, ctx.confidence, lat,
                        )
                        results[ctx.row_index] = self._build_result(ctx, t0)
                        continue

                    # ── 2.2  DB Exact Match ────────────────────────────────
                    t_sub = time.monotonic()
                    log.debug(f"[ROW #{i}]   {_S2} ↳ checking DB exact match for norm_occ=%r  eligible=%s", ctx.norm_occupation, ctx.eligible_sections)
                    db_hit = await self._reg.matcher.match_exact(ctx.norm_occupation, ctx.eligible_sections)
                    if db_hit and self._reg.rule_engine.validate_code(db_hit.code, ctx.education_level):
                        lat = (time.monotonic() - t_sub) * 1000
                        ctx.stage_latencies[_S2] = lat
                        ctx.matched_code = db_hit.code
                        ctx.matched_name = db_hit.name
                        ctx.matched_via  = MatchMethod.DB_EXACT_MATCH
                        ctx.confidence   = 1.0
                        ctx.is_resolved  = True
                        if hasattr(self._reg.cache, "set_exact"):
                            cache_res = CacheResult(
                                code=db_hit.code,
                                name=db_hit.name,
                                confidence=1.0,
                                matched_via=MatchMethod.DB_EXACT_MATCH,
                            )
                            await self._reg.cache.set_exact(ctx.cache_key, cache_res)
                        log.debug(
                            f"[ROW #{i}] ✓ {_S2} | HIT: db_exact  code=%s  name=%r | %.2fms",
                            db_hit.code, db_hit.name, lat,
                        )
                        results[ctx.row_index] = self._build_result(ctx, t0)
                        continue

                    # ── 2.3  Voyage Embedding (computed ONCE) ──────────────
                    t_sub = time.monotonic()
                    text_to_embed = f"{ctx.norm_occupation} {ctx.norm_activity}".strip()
                    log.debug(f"[ROW #{i}]   {_S2} ↳ embedding text=%r", text_to_embed)
                    ctx.query_embedding = await self._reg.embedder.embed_text(text_to_embed)
                    embed_ms = (time.monotonic() - t_sub) * 1000
                    log.debug(f"[ROW #{i}]   {_S2} ↳ embedding done  vec_dim=%d | %.2fms", len(ctx.query_embedding or []), embed_ms)

                    # ── 2.4  Semantic Cache (>= threshold) ────────────────
                    t_sub = time.monotonic()
                    sem_hit = await self._reg.cache.semantic_lookup(
                        ctx.query_embedding, ctx.education_level, threshold=self._settings.SEMANTIC_CACHE_THRESHOLD
                    )
                    if sem_hit and self._reg.rule_engine.validate_code(sem_hit.code, ctx.education_level):
                        lat = (time.monotonic() - t_sub) * 1000
                        ctx.stage_latencies[_S2] = lat
                        ctx.matched_code = sem_hit.code
                        ctx.matched_name = sem_hit.name
                        ctx.matched_via  = MatchMethod.SEMANTIC_CACHE
                        ctx.confidence   = sem_hit.confidence
                        ctx.is_resolved  = True
                        log.debug(
                            f"[ROW #{i}] ✓ {_S2} | HIT: semantic_cache  code=%s  name=%r  sim=%.4f | %.2fms",
                            sem_hit.code, sem_hit.name, sem_hit.confidence, lat,
                        )
                        results[ctx.row_index] = self._build_result(ctx, t0)
                        continue

                    # ── 2.5  In-Flight Deduplication ──────────────────────
                    t_sub = time.monotonic()
                    is_waiter, leader_id = await self._reg.cache.check_or_register_inflight(
                        request_id=ctx.request_id,
                        cache_key=ctx.cache_key,
                        query_vector=ctx.query_embedding,
                        norm_activity=ctx.norm_activity,
                        edu_level=ctx.education_level,
                        semantic_threshold=self._settings.SEMANTIC_INFLIGHT_THRESHOLD,
                    )

                    if is_waiter and leader_id:
                        log.debug(
                            f"[ROW #{i}]   {_S2} ↳ inflight_waiter  leader_id=%s  waiting...", leader_id,
                        )
                        inflight_res = await self._reg.cache.wait_for_inflight(
                            leader_id, timeout=self._settings.INFLIGHT_TIMEOUT_SECONDS
                        )
                        if inflight_res and self._reg.rule_engine.validate_code(inflight_res.code, ctx.education_level):
                            lat = (time.monotonic() - t_sub) * 1000
                            ctx.stage_latencies[_S2] = lat
                            ctx.matched_code = inflight_res.code
                            ctx.matched_name = inflight_res.name
                            if inflight_res.matched_via == MatchMethod.EXACT_CACHE:
                                ctx.matched_via = MatchMethod.EXACT_INFLIGHT_WAIT
                            else:
                                ctx.matched_via = MatchMethod.SEMANTIC_INFLIGHT_WAIT
                            ctx.confidence   = inflight_res.confidence
                            ctx.is_resolved  = True
                            log.debug(
                                f"[ROW #{i}] ✓ {_S2} | HIT: inflight_wait  via=%s  code=%s  name=%r | %.2fms",
                                ctx.matched_via.value, inflight_res.code, inflight_res.name, lat,
                            )
                            results[ctx.row_index] = self._build_result(ctx, t0)
                            continue
                        else:
                            log.debug(
                                f"[ROW #{i}]   {_S2} ↳ inflight_wait failed/timeout — falling through to LLM pipeline",
                            )

                else:
                    # Bypass cache: generate vector directly
                    text_to_embed = f"{ctx.norm_occupation} {ctx.norm_activity}".strip()
                    log.debug(f"[ROW #{i}]   {_S2} ↳ bypass_cache=True  embedding text=%r", text_to_embed)
                    ctx.query_embedding = await self._reg.embedder.embed_text(text_to_embed)

                ctx.stage_latencies[_S2] = (time.monotonic() - t0) * 1000
                log.debug(
                    f"[ROW #{i}] → {_S2} | MISS — pushing to LLM pipeline | %.2fms",
                    ctx.stage_latencies[_S2],
                )
                # Push to Stage 3: LLM Understanding
                await llm_queue.put(ctx)

            except Exception as exc:
                log.error(f"[ROW #{i}] ✗ {_S2} | ERROR: {exc}", exc_info=True)
                ctx.error_message = str(exc)
                ctx.final_code    = "999999"
                ctx.final_name    = "خطأ في الفرز المبدئي"
                ctx.final_method  = MatchMethod.FALLBACK
                await self._reg.cache.complete_inflight(ctx.request_id, None, error=exc)
                results[ctx.row_index] = self._build_result(ctx, t0)
            finally:
                raw_queue.task_done()

    # ─────────────────────────────────────────────────────────────────────────
    # Stage 3 + Stage 4 Worker: LLM Understanding + Rule Gate
    # ─────────────────────────────────────────────────────────────────────────
    async def _understand_worker(
        self,
        llm_queue: asyncio.Queue,
        retrieval_queue: asyncio.Queue,
        results: Dict[int, SingleCodingResult],
    ) -> None:
        """
        Stage 3 & Stage 4 Worker:
        LLM Understanding extracts formal work description and candidate Sections (1-9).
        Stage 4 Rule Gate applies education eligibility constraints.
        """
        while True:
            ctx: PipelineContext = await llm_queue.get()
            t0 = time.monotonic()
            i  = ctx.row_index
            try:
                # ── Stage 3: LLM Understanding ────────────────────────────
                t_s3 = time.monotonic()
                log.debug(
                    f"[ROW #{i}] ▶ {_S3} | IN: raw_occ=%r  raw_act=%r  raw_edu=%r",
                    ctx.raw_occupation, ctx.raw_activity, ctx.raw_education,
                )
                work_desc, sections = await self._reg.llm.understand_occupation(
                    ctx.raw_occupation, ctx.raw_activity, ctx.raw_education
                )
                ctx.work_description_formal = work_desc
                ctx.work_nature_sections    = sections
                s3_ms = (time.monotonic() - t_s3) * 1000
                ctx.stage_latencies[_S3] = s3_ms
                log.debug(
                    f"[ROW #{i}] ✓ {_S3} | OUT: work_desc=%r  llm_sections=%s | %.2fms",
                    work_desc, sections, s3_ms,
                )

                # ── Stage 4: Rule Gate ────────────────────────────────────
                t_s4 = time.monotonic()
                log.debug(
                    f"[ROW #{i}] ▶ {_S4} | IN: llm_sections=%s  edu_level=%s  edu_eligible=%s",
                    sections, ctx.education_level, ctx.eligible_sections,
                )
                gated_sections = self._reg.rule_engine.apply_gate(ctx.education_level, sections)
                ctx.eligible_sections = sorted(list(gated_sections)) if gated_sections else ctx.eligible_sections
                s4_ms = (time.monotonic() - t_s4) * 1000
                ctx.stage_latencies[_S4] = s4_ms
                log.debug(
                    f"[ROW #{i}] ✓ {_S4} | OUT: allowed_sections=%s (filtered from llm_sections=%s) | %.2fms",
                    ctx.eligible_sections, sections, s4_ms,
                )

                if not ctx.eligible_sections:
                    log.warning(
                        f"[ROW #{i}] ✗ {_S4} | All LLM-suggested sections blocked by education gate "
                        f"(edu_level={ctx.education_level}) — falling back to education-based sections",
                    )

                # Push to Stage 5: Restricted Vector Retrieval
                await retrieval_queue.put(ctx)

            except Exception as exc:
                log.error(f"[ROW #{i}] ✗ {_S3}/{_S4} | ERROR: {exc}", exc_info=True)
                ctx.error_message = str(exc)
                ctx.final_code    = "999999"
                ctx.final_name    = "خطأ في التحليل الدلالي"
                ctx.final_method  = MatchMethod.FALLBACK
                await self._reg.cache.complete_inflight(ctx.request_id, None, error=exc)
                results[ctx.row_index] = self._build_result(ctx, t0)
            finally:
                llm_queue.task_done()

    # ─────────────────────────────────────────────────────────────────────────
    # Stage 5 Worker: Restricted Vector Retrieval
    # ─────────────────────────────────────────────────────────────────────────
    async def _retrieval_worker(
        self,
        retrieval_queue: asyncio.Queue,
        select_queue: asyncio.Queue,
        results: Dict[int, SingleCodingResult],
    ) -> None:
        """
        Stage 5 Worker:
        Retrieves top-K ISCO candidates from pgvector, filtered by eligible sections.
        Filters out any candidate violating the education ceiling rule.
        """
        while True:
            ctx: PipelineContext = await retrieval_queue.get()
            t0 = time.monotonic()
            i  = ctx.row_index
            try:
                t_s5 = time.monotonic()
                log.debug(
                    f"[ROW #{i}] ▶ {_S5} | IN: eligible_sections=%s  top_k=%d  vec_dim=%d",
                    ctx.eligible_sections, self._settings.RETRIEVAL_TOP_K, len(ctx.query_embedding or []),
                )
                raw_candidates = await self._reg.retriever.retrieve(
                    query_vector=ctx.query_embedding,
                    eligible_sections=ctx.eligible_sections,
                    top_k=self._settings.RETRIEVAL_TOP_K,
                )

                # Ironclad Rule Gate filter: Discard any candidate that violates the education level!
                valid_candidates = [
                    c for c in raw_candidates
                    if self._reg.rule_engine.validate_code(c.code, ctx.education_level)
                ]
                ctx.candidates = valid_candidates
                s5_ms = (time.monotonic() - t_s5) * 1000
                ctx.stage_latencies[_S5] = s5_ms

                filtered_count = len(raw_candidates) - len(valid_candidates)
                log.debug(
                    f"[ROW #{i}] ✓ {_S5} | OUT: retrieved=%d  valid_after_gate=%d  filtered_by_edu=%d | %.2fms",
                    len(raw_candidates), len(valid_candidates), filtered_count, s5_ms,
                )
                if valid_candidates:
                    for rank, c in enumerate(valid_candidates[:5], 1):
                        log.debug(
                            f"[ROW #{i}]   {_S5}   candidate[{rank}]: code=%s  name=%r  sim=%.4f",
                            c.code, c.name, c.similarity,
                        )

                # Push to Stage 6: Final LLM Selection
                await select_queue.put(ctx)

            except Exception as exc:
                log.error(f"[ROW #{i}] ✗ {_S5} | ERROR: {exc}", exc_info=True)
                ctx.error_message = str(exc)
                ctx.final_code    = "999999"
                ctx.final_name    = "خطأ في الاسترجاع الشعاعي"
                ctx.final_method  = MatchMethod.FALLBACK
                await self._reg.cache.complete_inflight(ctx.request_id, None, error=exc)
                results[ctx.row_index] = self._build_result(ctx, t0)
            finally:
                retrieval_queue.task_done()

    # ─────────────────────────────────────────────────────────────────────────
    # Stage 6 Worker: Final LLM Selection
    # ─────────────────────────────────────────────────────────────────────────
    async def _select_worker(
        self,
        select_queue: asyncio.Queue,
        results: Dict[int, SingleCodingResult],
    ) -> None:
        """
        Stage 6 Worker:
        Final LLM Selection from Candidate hierarchical tree (names only).
        Assigns official code in Python, verifies education ceiling compliance, and updates cache.
        """
        while True:
            ctx: PipelineContext = await select_queue.get()
            t0 = time.monotonic()
            i  = ctx.row_index
            try:
                t_s6 = time.monotonic()
                log.debug(
                    f"[ROW #{i}] ▶ {_S6} | IN: num_candidates=%d  edu_level=%s",
                    len(ctx.candidates), ctx.education_level,
                )

                if not ctx.candidates:
                    ctx.final_code       = "999999"
                    ctx.final_name       = "غير مؤهل للمستوى المهني المطلوب"
                    ctx.final_confidence = 0.0
                    ctx.final_method     = MatchMethod.FALLBACK
                    ctx.selection_reasoning = (
                        f"لم يتم العثور على مرشحين متوافقين مع سقف المؤهل التعليمي "
                        f"({ctx.education_level}) والأقسام المسموحة."
                    )
                    s6_ms = (time.monotonic() - t_s6) * 1000
                    ctx.stage_latencies[_S6] = s6_ms
                    log.warning(
                        f"[ROW #{i}] ✗ {_S6} | No valid candidates after education gate — FALLBACK | %.2fms", s6_ms,
                    )
                    await self._reg.cache.complete_inflight(ctx.request_id, None)
                else:
                    row_ctx_str = (
                        f"المهنة الأصلية: {ctx.raw_occupation} | "
                        f"الوصف الوظيفي: {ctx.work_description_formal or ctx.raw_occupation} | "
                        f"النشاط: {ctx.raw_activity} | "
                        f"المؤهل: {ctx.raw_education}"
                    ).strip()

                    log.debug(
                        f"[ROW #{i}]   {_S6} ↳ calling LLM select_best  ctx_str=%r  num_cands=%d",
                        row_ctx_str[:120], len(ctx.candidates),
                    )

                    code, name, conf, reasoning = await self._reg.llm.select_best(
                        row_ctx_str, ctx.candidates
                    )
                    log.debug(
                        f"[ROW #{i}]   {_S6} ↳ LLM selected: code=%s  name=%r  conf=%.4f",
                        code, name, conf,
                    )

                    # Post-Selection Validation Gate: Python strictly enforces education ceiling!
                    if not self._reg.rule_engine.validate_code(code, ctx.education_level):
                        log.warning(
                            f"[ROW #{i}] ✗ {_S6} | edu_gate_violation: LLM chose code=%s (%r) "
                            f"which is FORBIDDEN for edu_level=%s — overriding!",
                            code, name, ctx.education_level,
                        )
                        valid_cands = [
                            c for c in ctx.candidates
                            if self._reg.rule_engine.validate_code(c.code, ctx.education_level)
                        ]
                        if valid_cands:
                            cand = valid_cands[0]
                            code, name, conf = cand.code, cand.name, cand.similarity
                            reasoning = (
                                f"تم استبدال اختيار الـ LLM تلقائياً بالمرشح المتوافق مع سقف المؤهل "
                                f"({ctx.education_level}): {name}"
                            )
                            log.warning(
                                f"[ROW #{i}]   {_S6} ↳ overridden to: code=%s  name=%r  conf=%.4f",
                                code, name, conf,
                            )
                        else:
                            code, name, conf = "999999", "غير مؤهل للمستوى المهني المطلوب", 0.0
                            reasoning = (
                                f"المسمى المختار يخالف سقف المؤهل التعليمي ({ctx.education_level})."
                            )
                            log.warning(
                                f"[ROW #{i}]   {_S6} ↳ no valid fallback candidate — FALLBACK 999999",
                            )

                    ctx.final_code       = code
                    ctx.final_name       = name
                    ctx.final_confidence = conf
                    ctx.final_method     = MatchMethod.LLM_PIPELINE
                    ctx.selection_reasoning = reasoning

                    s6_ms = (time.monotonic() - t_s6) * 1000
                    ctx.stage_latencies[_S6] = s6_ms
                    log.debug(
                        f"[ROW #{i}] ✓ {_S6} | OUT: code=%s  name=%r  conf=%.4f | %.2fms",
                        code, name, conf, s6_ms,
                    )

                    # Save result into cache and awaken any waiters
                    cache_res = CacheResult(
                        code=code,
                        name=name,
                        confidence=conf,
                        matched_via=MatchMethod.LLM_PIPELINE,
                    )
                    await self._reg.cache.complete_inflight(ctx.request_id, cache_res)

                results[ctx.row_index] = self._build_result(ctx, t0)

            except Exception as exc:
                log.error(f"[ROW #{i}] ✗ {_S6} | ERROR: {exc}", exc_info=True)
                ctx.error_message = str(exc)
                ctx.final_code    = "999999"
                ctx.final_name    = "خطأ في الاختيار النهائي"
                ctx.final_method  = MatchMethod.FALLBACK
                await self._reg.cache.complete_inflight(ctx.request_id, None, error=exc)
                results[ctx.row_index] = self._build_result(ctx, t0)
            finally:
                select_queue.task_done()

    # ─────────────────────────────────────────────────────────────────────────
    # Result Builder — emits per-row TRACE SUMMARY at INFO level
    # ─────────────────────────────────────────────────────────────────────────
    def _build_result(self, ctx: PipelineContext, start_t: float) -> SingleCodingResult:
        """Constructs SingleCodingResult without hierarchy columns and emits trace summary."""
        elapsed_ms = (time.monotonic() - start_t) * 1000.0
        ctx.processing_time_ms = elapsed_ms

        code   = ctx.final_code   or ctx.matched_code or "999999"
        name   = ctx.final_name   or ctx.matched_name or "غير محدد"
        conf   = ctx.final_confidence if ctx.final_confidence > 0 else (ctx.confidence if ctx.confidence > 0 else 0.0)
        method = ctx.final_method.value if ctx.final_method else (ctx.matched_via.value if ctx.matched_via else "unknown")

        # ── Per-row TRACE SUMMARY ─────────────────────────────────────────
        stages_passed = " → ".join(
            f"{stage}({ms:.1f}ms)" for stage, ms in ctx.stage_latencies.items()
        )
        log.info(
            "[ROW #%d] TRACE | input=%r | edu=%s | sections=%s | "
            "stages: %s | result: code=%s  name=%r  via=%s  conf=%.4f | total=%.2fms%s",
            ctx.row_index,
            ctx.raw_occupation,
            ctx.education_level,
            ctx.eligible_sections,
            stages_passed if stages_passed else "(resolved early)",
            code,
            name,
            method,
            conf,
            elapsed_ms,
            f" | ERROR: {ctx.error_message}" if ctx.error_message else "",
        )

        return SingleCodingResult(
            row_index=ctx.row_index,
            assigned_code=code,
            assigned_name=name,
            confidence=round(conf, 4),
            matched_via=method,
            education_level=ctx.education_level,
            eligible_sections=ctx.eligible_sections,
            processing_time_ms=round(elapsed_ms, 2),
            selection_reasoning=ctx.selection_reasoning or "",
            error=ctx.error_message,
        )

    def _compute_metrics(self, results: List[SingleCodingResult], duration_ms: float) -> BatchSummaryMetrics:
        """Aggregates execution performance and routing counts."""
        total         = len(results)
        exact_cache   = sum(1 for r in results if r.matched_via == MatchMethod.EXACT_CACHE.value)
        db_match      = sum(1 for r in results if r.matched_via == MatchMethod.DB_EXACT_MATCH.value)
        sem_cache     = sum(1 for r in results if r.matched_via == MatchMethod.SEMANTIC_CACHE.value)
        exact_inflight = sum(1 for r in results if r.matched_via == MatchMethod.EXACT_INFLIGHT_WAIT.value)
        sem_inflight  = sum(1 for r in results if r.matched_via == MatchMethod.SEMANTIC_INFLIGHT_WAIT.value)
        llm_count     = sum(1 for r in results if r.matched_via == MatchMethod.LLM_PIPELINE.value)

        avg_time = (duration_ms / total) if total > 0 else 0.0

        return BatchSummaryMetrics(
            total_rows=total,
            exact_cache_hits=exact_cache,
            db_match_hits=db_match,
            semantic_cache_hits=sem_cache,
            exact_inflight_waits=exact_inflight,
            semantic_inflight_waits=sem_inflight,
            llm_processed_count=llm_count,
            total_duration_ms=round(duration_ms, 2),
            average_row_time_ms=round(avg_time, 2),
        )
