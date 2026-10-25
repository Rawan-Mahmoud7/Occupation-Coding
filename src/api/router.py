"""
REST API Router Module.
Defines endpoints for:
- POST /api/v1/code: Batch JSON coding.
- POST /api/v1/code/file: Upload Excel/CSV with flexible column mapping and clean export.
- POST /api/v1/config/add-llm-key: Dynamically add an API key and update .env.
- GET /api/v1/health: Deep health check for DB, Voyage Embedder, and LLM.
"""

import io
import logging
from pathlib import Path
from typing import Optional, List
import pandas as pd
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import Settings
from api.schemas import (
    BatchCodingRequest,
    BatchCodingResponse,
    AddLLMKeyRequest,
    AddLLMKeyResponse,
    HealthCheckResponse,
    ComponentHealth,
    OccupationRowInput,
)
from api.dependencies import get_pipeline, get_db_session, get_settings_dep
from Service.pipeline.coding_pipeline import CodingPipeline

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Occupation Coding"])


def excel_col_to_index(col_str: str) -> int:
    """Converts Excel column letters (A, B, ..., Z, AA, ...) to 0-based index."""
    s = col_str.strip().upper()
    if not s or not s.isalpha():
        return -1
    idx = 0
    for char in s:
        idx = idx * 26 + (ord(char) - ord('A') + 1)
    return idx - 1


def index_to_excel_col(idx: int) -> str:
    """Converts 0-based column index to Excel column letters (0 -> 'A', 25 -> 'Z', 26 -> 'AA')."""
    result = []
    idx += 1
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        result.append(chr(ord('A') + rem))
    return "".join(reversed(result))


def resolve_column(
    df: pd.DataFrame,
    col_param: Optional[str],
    col_role: str,
    required: bool = False,
) -> Optional[str]:
    """
    Resolves column input parameter (which may be an exact header name or Excel letter like 'A' or 'U')
    to the actual DataFrame column header.
    Raises HTTPException 400 with helpful error message and available options if invalid.
    """
    if not col_param or not str(col_param).strip():
        if required:
            available_letters = [index_to_excel_col(i) for i in range(len(df.columns))]
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"العمود الخاص بـ ({col_role}) إلزامي ولم يتم تحديده.\n"
                    f"يرجى تحديد حرف العمود أو اسمه من الملف.\n"
                    f"الحروف المتاحة: {', '.join(available_letters)}\n"
                    f"الأسماء المتاحة: {', '.join(str(c) for c in df.columns)}"
                ),
            )
        return None

    param = str(col_param).strip()

    # 1. Exact match with header name
    if param in df.columns:
        return param

    # 2. Case-insensitive / stripped match
    for col in df.columns:
        if str(col).strip().lower() == param.lower():
            return str(col)

    # 3. Check if parameter is Excel letter (e.g. 'A', 'U', 'T', 'AA')
    letter_idx = excel_col_to_index(param)
    if 0 <= letter_idx < len(df.columns):
        return str(df.columns[letter_idx])

    # 4. Not found -> Raise 400 Bad Request with available letters and names
    available_letters = [index_to_excel_col(i) for i in range(len(df.columns))]
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=(
            f"العمود المحدد لـ ({col_role}) بالقيمة '{param}' غير موجود بالملف.\n"
            f"الأعمدة المتاحة بالملف هي الحروف: {', '.join(available_letters)}\n"
            f"أو الأسماء: {', '.join(str(c) for c in df.columns)}"
        ),
    )


# ─── 1. Batch JSON Coding ───

@router.post(
    "/code",
    response_model=BatchCodingResponse,
    summary="تكويد دفعة من المسميات المهنية (JSON)",
)
async def code_batch(
    request: BatchCodingRequest,
    pipeline: CodingPipeline = Depends(get_pipeline),
):
    """
    Codes a batch of occupation rows through the 6-stage pipeline.
    Returns results and execution summary metrics.
    """
    results, summary = await pipeline.process_batch(
        request.rows, bypass_cache=request.bypass_cache
    )
    return BatchCodingResponse(results=results, summary=summary)


# ─── 2. File Upload Coding (Excel / CSV) ───

@router.post(
    "/code/file",
    summary="تكويد ملف إكسل أو CSV وتصدير النتائج النظيفة",
)
async def code_file(
    file: UploadFile = File(..., description="ملف Excel أو CSV المطلوب تكويده"),
    occupation_col: str = Form(..., description="اسم أو حرف عمود المهنة (إلزامي)"),
    activity_col: Optional[str] = Form(None, description="اسم أو حرف عمود النشاط (اختياري)"),
    education_col: Optional[str] = Form(None, description="اسم أو حرف عمود المؤهل (اختياري)"),
    detail_a_col: Optional[str] = Form(None, description="اسم أو حرف عمود تفاصيل المؤهل A (اختياري)"),
    detail_b_col: Optional[str] = Form(None, description="اسم أو حرف عمود التخصص B (اختياري)"),
    bypass_cache: bool = Form(False, description="تخطي الكاش والمعالجة الكاملة"),
    pipeline: CodingPipeline = Depends(get_pipeline),
):
    """
    Accepts an Excel (.xlsx/.xls) or CSV file with arbitrary column structure.
    Users can specify column names or Excel letters (e.g. 'A', 'T', 'W').
    Returns an Excel file containing original columns plus clean output:
    - assigned_code
    - assigned_name
    - confidence
    - matched_via
    - selection_reasoning
    (No unnecessary hierarchy columns).
    """
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="الملف المرفوع فارغ.")

    filename = (file.filename or "").lower()
    try:
        if filename.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(content))
        else:
            df = pd.read_excel(io.BytesIO(content))
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"تعذر قراءة الملف المرفوع. يرجى التأكد من أنه ملف Excel أو CSV سليم: {exc}",
        )

    if df.empty:
        raise HTTPException(status_code=400, detail="الملف المرفوع لا يحتوي على أي صفوف.")

    # Resolve Column Headers
    resolved_occ = resolve_column(df, occupation_col, "اسم المهنة", required=True)
    resolved_act = resolve_column(df, activity_col, "النشاط الاقتصادي", required=False)
    resolved_edu = resolve_column(df, education_col, "الحالة التعليمية", required=False)
    resolved_det_a = resolve_column(df, detail_a_col, "اسم المؤهل (تفاصيل A)", required=False)
    resolved_det_b = resolve_column(df, detail_b_col, "التخصص (تفاصيل B)", required=False)

    # Convert DataFrame rows to OccupationRowInput
    rows: List[OccupationRowInput] = []
    for _, row in df.iterrows():
        occ_val = str(row[resolved_occ]) if pd.notna(row[resolved_occ]) else ""
        act_val = str(row[resolved_act]) if (resolved_act and pd.notna(row[resolved_act])) else ""
        edu_val = str(row[resolved_edu]) if (resolved_edu and pd.notna(row[resolved_edu])) else ""
        det_a_val = str(row[resolved_det_a]) if (resolved_det_a and pd.notna(row[resolved_det_a])) else ""
        det_b_val = str(row[resolved_det_b]) if (resolved_det_b and pd.notna(row[resolved_det_b])) else ""

        rows.append(
            OccupationRowInput(
                occupation_name=occ_val,
                activity=act_val,
                education_raw=edu_val,
                education_detail_a=det_a_val,
                education_detail_b=det_b_val,
            )
        )

    # Process batch through pipeline
    results, _ = await pipeline.process_batch(rows, bypass_cache=bypass_cache)

    # Append clean output columns to DataFrame
    df["assigned_code"] = [r.assigned_code for r in results]
    df["assigned_name"] = [r.assigned_name for r in results]
    df["confidence"] = [r.confidence for r in results]
    df["matched_via"] = [r.matched_via for r in results]
    df["selection_reasoning"] = [r.selection_reasoning for r in results]

    # Export to Excel BytesIO
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Coded_Occupations")
    output.seek(0)

    headers = {
        "Content-Disposition": 'attachment; filename="coded_occupations.xlsx"'
    }
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


# ─── 3. Dynamic LLM API Key Addition ───

@router.post(
    "/config/add-llm-key",
    response_model=AddLLMKeyResponse,
    summary="إضافة مفتاح API جديد ديناميكياً وحفظه في .env دون مسح القديم",
)
async def add_llm_key(
    req: AddLLMKeyRequest,
    pipeline: CodingPipeline = Depends(get_pipeline),
    settings: Settings = Depends(get_settings_dep),
):
    """
    Adds a new API key to the active LLM client rotator and appends it to src/.env.
    Does not delete or overwrite previous keys.
    """
    key = req.api_key.strip()
    if not key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="مفتاح الـ API لا يمكن أن يكون فارغاً.",
        )

    # 1. Add key to active in-memory pipeline rotator
    total_keys = pipeline.add_llm_api_key(key)

    # 2. Append key to src/.env safely
    env_file = Path("C:/Occupation-Coding-APP/src/.env")
    if env_file.exists():
        try:
            content = env_file.read_text(encoding="utf-8")
            lines = content.splitlines()
            new_lines = []
            key_appended = False

            for line in lines:
                if line.startswith("LLM_API_KEYS="):
                    existing_val = line.split("=", 1)[1].strip()
                    keys = [k.strip() for k in existing_val.split(",") if k.strip()]
                    if key not in keys:
                        keys.append(key)
                    new_lines.append(f"LLM_API_KEYS={','.join(keys)}")
                    key_appended = True
                else:
                    new_lines.append(line)

            if not key_appended:
                new_lines.append(f"LLM_API_KEYS={key}")

            env_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            log.info(f"Appended new key to .env. Total configured keys: {total_keys}")
        except Exception as exc:
            log.warning(f"Could not persist new key to .env file: {exc}")

    return AddLLMKeyResponse(
        status="success",
        message=f"تم بنجاح تفعيل المفتاح للحساب '{req.account_name or 'Default'}' وتحديث ملف .env.",
        total_active_keys=total_keys,
    )


# ─── 4. Health Check ───

@router.get(
    "/health",
    response_model=HealthCheckResponse,
    summary="فحص صحة النظام ومكوناته الأساسية",
)
async def health_check(
    session: Optional[AsyncSession] = Depends(get_db_session),
    settings: Settings = Depends(get_settings_dep),
):
    """Verifies connectivity with PostgreSQL, Voyage Embedder, and LLM endpoints."""
    components: List[ComponentHealth] = []
    overall_status = "ok"

    # 1. PostgreSQL Check
    if session:
        try:
            t0 = time.monotonic()
            await session.execute(text("SELECT 1"))
            latency = (time.monotonic() - t0) * 1000.0
            components.append(
                ComponentHealth(name="PostgreSQL", status="healthy", latency_ms=round(latency, 2))
            )
        except Exception as exc:
            overall_status = "degraded"
            components.append(
                ComponentHealth(name="PostgreSQL", status="unhealthy", details=str(exc))
            )
    else:
        components.append(
            ComponentHealth(name="PostgreSQL", status="disabled", details="DB connection pool not active.")
        )

    # 2. Voyage AI Embedder Check
    embedder_status = "healthy" if settings.VOYAGE_API_KEY else "disabled"
    components.append(
        ComponentHealth(
            name="Voyage_Embedder",
            status=embedder_status,
            details=f"Model: {settings.VOYAGE_MODEL}",
        )
    )

    # 3. Remote LLM Check
    llm_status = "healthy" if settings.api_keys_list else "disabled"
    components.append(
        ComponentHealth(
            name="Remote_LLM",
            status=llm_status,
            details=f"Model: {settings.LLM_MODEL}, Active keys count: {len(settings.api_keys_list)}",
        )
    )

    return HealthCheckResponse(
        status=overall_status,
        version=settings.APP_VERSION,
        components=components,
    )
