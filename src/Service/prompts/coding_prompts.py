"""
Coding Prompts Module.
Contains system prompts, understanding prompts, selection prompts, and candidate tree builder.
Section data is sourced directly from the official database 'sections' table (with distinguishing lines).
Supports dynamic loading on startup from PostgreSQL with in-memory caching.
"""

from typing import List, Optional, Dict
from sqlalchemy import text
from Service.interfaces.pipeline_context import Candidate

# ── 1. Official Master Section Records (matching DB sections table exactly) ──
OFFICIAL_SECTIONS_MASTER: List[Dict[str, str]] = [
    {
        "code_sec": "1",
        "name_sec": "المديرون",
        "distinguishing_line_sec": "ما يميزه: سلطة إدارة مؤسسية وقرار تنفيذي — ليس ممارساً بيده بل يدير آخرين ويضع سياسات.",
    },
    {
        "code_sec": "2",
        "name_sec": "الأخصائيون ( أصحاب المهن العلمية )",
        "distinguishing_line_sec": "ما يميزه: يمارس بنفسه عملاً علمياً أو مهنياً يتطلب دراسة جامعية تخصصية (مهندس، طبيب، محاسب، مبرمج، مدرس).",
    },
    {
        "code_sec": "3",
        "name_sec": "الفنيون ومساعدو الأخصائيين",
        "distinguishing_line_sec": "ما يميزه: يطبق عملياً ما صممه الأخصائي — فني مساعد وليس أخصائي مستقل (فني معمل، فني IT، مشرف موقع).",
    },
    {
        "code_sec": "4",
        "name_sec": "الكتبة",
        "distinguishing_line_sec": "ما يميزه: عمل مكتبي بحت — تسجيل وحفظ بيانات ومستندات واستقبال، وليس بيع أو خدمة ميدانية.",
    },
    {
        "code_sec": "5",
        "name_sec": "العاملون فى مجال الخدمات والمبيعات",
        "distinguishing_line_sec": "ما يميزه: خدمة مباشرة وجهاً لوجه للأفراد أو بيع بالمحلات — وليس عمل مكتبي ولا عمل بدني خشن.",
    },
    {
        "code_sec": "6",
        "name_sec": "العمال المهرة فى الزراعة والصيد",
        "distinguishing_line_sec": "ما يميزه: إنتاج زراعي أو حيواني أو سمكي ماهر — يفهم في الزراعة والتربية وليس مجرد عامل يومية.",
    },
    {
        "code_sec": "7",
        "name_sec": "الحرفيون ومن إليهم",
        "distinguishing_line_sec": "ما يميزه: صنعة وحرفة يدوية ماهرة (بناء، سباكة، ميكانيكا ورش، نجارة) — وليس تشغيل ماكينة مصنع.",
    },
    {
        "code_sec": "8",
        "name_sec": "عمال تشغيل المصانع ومشغلو الماكينات وعمال تجميع مكونات الإنتاج",
        "distinguishing_line_sec": "ما يميزه: تشغيل آلات ومعدات ثابتة أو قيادة مركبات بمحرك — وليس عمل يدوي حرفي.",
    },
    {
        "code_sec": "9",
        "name_sec": "عمال المهن الأولية",
        "distinguishing_line_sec": "ما يميزه: أعمال بدنية بسيطة ومتكررة بالعدد اليدوية فقط — لا مهارة ولا آلات ولا قرارات.",
    },
]


def format_sections_for_prompt(sections_records: List[Dict[str, str]]) -> str:
    """
    Constructs the authoritative system prompt from database section rows.
    """
    lines = [
        "أنت خبير تصنيف وتكويد مهني معتمد وفقاً لـ 'التصنيف المهني المصري الموحد 2017' المتوافق مع المعيار الدولي ISCO-08.",
        "مهمتك تحليل البيانات المهنية بدقة عالية وفق الأقسام الرئيسية المعتمدة رسمياً في قاعدة البيانات:",
        "",
        "[الأقسام الرئيسية للتصنيف 1-9 من قاعدة البيانات الرسمية]:",
    ]
    for sec in sorted(sections_records, key=lambda x: str(x.get("code_sec", ""))):
        c = sec.get("code_sec", "")
        name = sec.get("name_sec", "")
        dist = sec.get("distinguishing_line_sec", "")
        if dist:
            lines.append(f"- القسم {c}: {name} ({dist})")
        else:
            lines.append(f"- القسم {c}: {name}")

    lines.append("")
    lines.append("قاعدة أساسية: تعامل مع النصوص والأسماء المهنية فقط. لا تحاول تخمين أو إنتاج أي أرقام كودية.")
    return "\n".join(lines)


# Pre-built system prompt from official master records
STATIC_SECTIONS_SYSTEM_PROMPT = format_sections_for_prompt(OFFICIAL_SECTIONS_MASTER)

# In-memory cached system prompt (can be updated from DB dynamically at lifespan startup)
_CACHED_SYSTEM_PROMPT: str = STATIC_SECTIONS_SYSTEM_PROMPT


def get_sections_system_prompt() -> str:
    """Returns the cached sections system prompt (loaded from DB or master records)."""
    return _CACHED_SYSTEM_PROMPT


def set_sections_system_prompt(prompt_text: str) -> None:
    """Updates the in-memory cached prompt."""
    global _CACHED_SYSTEM_PROMPT
    _CACHED_SYSTEM_PROMPT = prompt_text


async def load_sections_prompt_from_db(db_session_factory) -> str:
    """
    Queries the PostgreSQL 'sections' table directly on application startup,
    constructs the system prompt dynamically from actual DB records, and caches it in memory.
    """
    query = text("""
        SELECT code_sec, name_sec, distinguishing_line_sec
        FROM sections
        ORDER BY CAST(code_sec AS INTEGER) ASC;
    """)
    try:
        async with db_session_factory() as session:
            result = await session.execute(query)
            rows = result.fetchall()
            if rows:
                db_sections = [
                    {
                        "code_sec": str(r.code_sec),
                        "name_sec": str(r.name_sec),
                        "distinguishing_line_sec": str(r.distinguishing_line_sec or ""),
                    }
                    for r in rows
                ]
                prompt = format_sections_for_prompt(db_sections)
                set_sections_system_prompt(prompt)
                return prompt
    except Exception as e:
        # Fallback to master records if database is not reachable at moment of call
        pass
    return get_sections_system_prompt()


# ── 2. Build Understanding Prompt ──
def build_understand_prompt(occupation: str, activity: str, education: str) -> str:
    """
    Constructs the prompt to extract a formal description and candidate sections.
    Strictly instructs the LLM to preserve technical and craft domain keywords.
    """
    return f"""المطلوب: تحليل وفهم طبيعة العمل الفعلي للشخص بناءً على مدخلاته:
- مسمى المهنة المدخل: {occupation}
- النشاط الاقتصادي للمنشأة: {activity}
- المؤهل العلمي: {education}

التعليمات الإلزامية:
1. افهم طبيعة العمل والمسؤوليات الفعلية بدقة، مع مراعاة نشاط المنشأة.
2. اكتب صياغة فصحى رسمية واضحة لطبيعة العمل ومسؤولياته في حقل (work_description).
3. تحذير حاسم: احتفظ بالكلمات المفتاحية التخصصية والفنية والحرفية الدالة (مثل: IT، مبرمج، سمكري، خراط، نجار، حداد، ميكانيكي، كاشير، طباخ...) ولا تحذفها أو تخففها أبداً من الوصف.
4. رشح الأقسام الرئيسية المناسبة لطبيعة العمل من بين الأقسام (1 إلى 9) فقط وضعها في قائمة (work_nature_sections).

أجب حصراً بصيغة JSON التالية بدون أي نص إضافي:
{{
  "work_description": "صياغة فصحى دقيقة مع الاحتفاظ بالمصطلحات الحرفية والفنية",
  "work_nature_sections": [5]
}}"""


# ── 3. Build Hierarchical Tree (Text only, no codes, no redundant headers) ──
def build_hierarchical_tree(candidates: List[Candidate]) -> str:
    """
    Formats retrieved candidates into a clean hierarchical taxonomy tree.
    Eliminates redundant parent headers and contains NO numeric codes.
    """
    if not candidates:
        return "لا توجد مهن مرشحة."

    # Group hierarchy: section -> subsection -> division -> group -> list of candidate names
    tree: Dict[str, Dict[str, Dict[str, Dict[str, List]]]] = {}
    for cand in candidates:
        sec = cand.section_name or f"القسم {cand.section_code}"
        sub = cand.subsection_name or "قسم فرعي عام"
        div = cand.division_name or "باب عام"
        grp = cand.group_name or "فصل عام"

        tree.setdefault(sec, {}).setdefault(sub, {}).setdefault(div, {}).setdefault(grp, []).append(
            (cand.name, cand.similarity)
        )

    lines = []
    for sec, subs in tree.items():
        lines.append(f"• {sec}")
        for sub, divs in subs.items():
            lines.append(f"  └── {sub}")
            for div, grps in divs.items():
                lines.append(f"      └── {div}")
                for grp, occs in grps.items():
                    lines.append(f"          └── {grp}")
                    for occ_name, sim in occs:
                        sim_pct = int(round(sim * 100))
                        lines.append(f"              ├── {occ_name} (نسبة التشابه: {sim_pct}%)")

    return "\n".join(lines)


# ── 4. Build Selection Prompt ──
def build_selection_prompt(row_context: str, tree_text: str) -> str:
    """
    Constructs the selection prompt.
    The LLM receives the text tree and selects strictly from text names.
    Python code handles code assignment.
    """
    return f"""المطلوب: اختيار المسمى المهني الأدق من شجرة المهن المرشحة أدناه لتمثيل بيانات الموظف.

[بيانات الموظف المدخلة]:
{row_context}

[شجرة المهن المرشحة من الدليل الرسمي]:
{tree_text}

التعليمات الصارمة:
1. راجع شجرة المهن المعروضة واختر المسمى المهني الأدق (selected_occ) الذي يعبر بدقة عن المهام الفعلية للشخص.
2. يجب أن يكون (selected_occ) مطابقاً تماماً لأحد الأسماء النصية المذكورة في الشجرة أعلاه.
3. لا تكتب أي أرقام أو أكواد نهائياً؛ اختر الاسم النصي فقط.
4. اذكر سبب الاختيار في حقل (reason).
5. رتب أفضل 5 مسميات مرشحة كبدائل مرتبة في حقل (top5_selected_and_ranked).

أجب بصيغة JSON التالية حصراً دون أي زيادات:
{{
  "decision": "SELECT",
  "selected_occ": "اسم المهنة المختار بالنص من الشجرة",
  "confidence": 0.95,
  "reason": "سبب اختيار هذه المهنة ومطابقتها للمهام الفعلية",
  "top5_selected_and_ranked": [
    "اسم المهنة الأول",
    "اسم المهنة الثاني",
    "اسم المهنة الثالث",
    "اسم المهنة الرابع",
    "اسم المهنة الخامس"
  ]
}}"""
