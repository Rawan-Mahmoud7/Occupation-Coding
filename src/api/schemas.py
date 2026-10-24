"""
API Schemas Module.
Defines Pydantic v2 request/response models and health check contracts.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


# ── 1. Request Models ──

class OccupationRowInput(BaseModel):
    """Input payload for a single occupation row (real input fields only)."""
    occupation_name: str = Field(..., description="المسمى المهني المدخل")
    activity: Optional[str] = Field(default="", description="النشاط الاقتصادي للمنشأة")
    education_raw: Optional[str] = Field(default="", description="المؤهل التعليمي الخام")
    education_detail_a: Optional[str] = Field(default="", description="تخصص المؤهل إن وجد")
    education_detail_b: Optional[str] = Field(default="", description="تفاصيل إضافية عن المؤهل")


class BatchCodingRequest(BaseModel):
    """Request payload for batch occupation coding."""
    rows: List[OccupationRowInput] = Field(..., description="قائمة الصفوف المطلوب تكويدها")
    bypass_cache: bool = Field(default=False, description="تخطي الكاش وإجبار المرور بالخط كاملاً")


# ── 2. Response Models ──

class SingleCodingResult(BaseModel):
    """Coding output for a single row including complete hierarchy names."""
    row_index: int = Field(..., description="ترتيب الصف في الدفعة الأصلية")
    assigned_code: str = Field(..., description="الرمز المهني المعتمد (6 أو 7 أرقام)")
    assigned_name: str = Field(..., description="المسمى الرسمي المعتمد في الدليل المصري")
    section_name: str = Field(default="", description="اسم القسم الرئيسي")
    subsection_name: str = Field(default="", description="اسم القسم الفرعي")
    division_name: str = Field(default="", description="اسم الباب")
    group_name: str = Field(default="", description="اسم الفصل / المجموعة")
    confidence: float = Field(..., description="نسبة الثقة في النتيجة (0.0 إلى 1.0)")
    matched_via: str = Field(..., description="طريقة التكويد (exact_cache, db_exact_match, semantic_cache, exact_inflight_wait, semantic_inflight_wait, llm_pipeline)")
    education_level: str = Field(..., description="المستوى التعليمي المعياري المحسوب")
    eligible_sections: List[int] = Field(default_factory=list, description="الأقسام الرئيسية المؤهلة")
    processing_time_ms: float = Field(..., description="زمن معالجة هذا السجل بالمللي ثانية")
    selection_reasoning: Optional[str] = Field(default="", description="سبب اختيار الرمز")
    error: Optional[str] = Field(default=None, description="رسالة الخطأ إن تعذر التكويد")


class BatchSummaryMetrics(BaseModel):
    """Execution performance and accuracy metrics for the batch."""
    total_rows: int = Field(..., description="إجمالي عدد الصفوف")
    exact_cache_hits: int = Field(default=0, description="حالات الكاش الحرفي الفوري O(1)")
    db_match_hits: int = Field(default=0, description="حالات التطابق مع قاعدة البيانات المباشرة")
    semantic_cache_hits: int = Field(default=0, description="حالات الكاش الدلالي (>= 98%)")
    exact_inflight_waits: int = Field(default=0, description="الطلبات المماثلة التي انتظرت طلباً جارياً")
    semantic_inflight_waits: int = Field(default=0, description="الطلبات المقاربة دلالياً التي انتظرت طلباً جارياً")
    llm_processed_count: int = Field(default=0, description="الحالات التي دخلت مسار الـ LLM الكامل")
    total_duration_ms: float = Field(..., description="الزمن الكلي لمعالجة الدفعة بالمللي ثانية")
    average_row_time_ms: float = Field(..., description="متوسط زمن الصف الواحد بالمللي ثانية")


class BatchCodingResponse(BaseModel):
    """Complete batch coding response with individual results and summary metrics."""
    results: List[SingleCodingResult]
    summary: BatchSummaryMetrics


# ── 3. Health Check Models ──

class ComponentHealth(BaseModel):
    name: str
    status: str       # "healthy" | "unhealthy" | "disabled"
    latency_ms: Optional[float] = None
    details: Optional[str] = None


class HealthCheckResponse(BaseModel):
    status: str       # "ok" | "degraded" | "down"
    version: str
    components: List[ComponentHealth]
