"""
Coding Prompts Module.
Contains system prompts, understanding prompts, selection prompts, and candidate tree builder.
All LLM prompts deal strictly with text; numeric codes are managed by Python code.
"""

import json
from typing import List
from Service.interfaces.pipeline_context import Candidate


# ── 1. Static Sections System Prompt (Cached prefix for LLM Prompt Caching) ──
STATIC_SECTIONS_SYSTEM_PROMPT = """أنت خبير تصنيف وتكويد مهني معتمد وفقاً لـ "التصنيف المهني المصري الموحد 2017" المتوافق مع المعيار الدولي ISCO-08.
مهمتك تحليل البيانات المهنية بدقة عالية وفق الأقسام الرئيسية التسعة التالية:

[الأقسام الرئيسية للتصنيف 1-9]:
- القسم 1: المديرون (يشمل مديري العموم، الإدارات، المؤسسات، ومديري الإنتاج والعمليات).
- القسم 2: الاختصاصيون / المحترفون (يشمل المهن الفكرية والعلمية العليا التي تتطلب مؤهلاً جامعياً كالأطباء، المهندسين، المبرمجين، المحامين، والأساتذة).
- القسم 3: الفنيون ومساعدو الاختصاصيين (يشمل الأعمال الفنية والمساعدين التقنيين كمشرفي العمليات، مساعدي التمريض، والمساحين وفنيي المعامل).
- القسم 4: موظفو الدعم المكتبي والكتبة (يشمل موظفي خدمة العملاء، الكاشير، المحاسبين المساعدين، كتبة المخازن والأرشيف والسكرتارية).
- القسم 5: عمال البيع والخدمات (يشمل البائعين في المتاجر والمولات، مضيفي المطاعم، عمال النظافة الفندقية، الحراس، ورجال الشرطة والإطفاء).
- القسم 6: العمال المهرة في الزراعة والصيد والغابات (يشمل مزارعي المحاصيل، مربي الماشية والدواجن، والصيادين التجاريين).
- القسم 7: عمال الحرف والمهن اليدوية المرتبطة بها (يشمل البنائين، النجارين، الحدادين، الخراطين، السباكين، اللحامين، السمكرية، والكهربائيين).
- القسم 8: مشغلو الآلات ومجمعو المعدات وسائقو المركبات (يشمل سائقي الشاحنات والحافلات، مشغلي المكابس والمصانع وعمال خطوط التجميع الآلية).
- القسم 9: عمال المهن الأولية (يشمل العمالة غير الماهرة كعمال البناء اليدوي، الشيالين، عمال النظافة العامة، وحراس الأمن البسيطين).

قاعدة أساسية: تعامل مع النصوص والأسماء المهنية فقط. لا تحاول تخمين أو إنتاج أي أرقام كودية.
"""


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
    tree = {}
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
