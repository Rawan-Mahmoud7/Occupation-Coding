"""
Excel → PostgreSQL data import script.

Reads occupation hierarchy data from the Excel workbook and inserts
it into the existing SQLAlchemy-modelled tables, respecting the
cascade:

    Section → Subsection → Division → Group → Occupation

Safe to run multiple times (idempotent – skips existing records by code).
"""

import os
import sys
import logging

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# ---------------------------------------------------------------------------
# Path setup – make the scheme package importable
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_SCHEME_PARENT = os.path.join(_SCRIPT_DIR, "Service", "models", "dbschemes")
sys.path.insert(0, _SCHEME_PARENT)

# pyrefly: ignore [missing-import]
from scheme import SQLAlchemyBase, Section, Subsection, Division, Group, Occupation

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
EXCEL_PATH = os.path.join(
    os.path.dirname(_SCRIPT_DIR),
    "المهن 2017_updated.xlsx",
)

POSTGRES_URL = (
    "postgresql+psycopg2://"
    "postgres:oc_coding_pgvector_90@localhost:5432/oc_coding"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-8s %(message)s",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _code_str(value, width: int) -> str:
    """Convert a numeric cell to a zero-padded string of *width* digits."""
    return str(int(value)).zfill(width)


def _clean_text(value) -> str | None:
    """Return stripped text or ``None`` for empty / NaN cells."""
    if pd.isna(value):
        return None
    text = str(value).strip()
    return text if text else None


# ---------------------------------------------------------------------------
# Import logic
# ---------------------------------------------------------------------------

def import_data() -> None:

    engine = create_engine(POSTGRES_URL)
    SQLAlchemyBase.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        _import_sections(session)
        _import_subsections(session)
        _import_groups_and_divisions(session)
        _import_occupations(session)
        session.commit()
        log.info("Import completed successfully.")
    except Exception:
        session.rollback()
        log.exception("Import failed – rolled back.")
        raise
    finally:
        session.close()
        engine.dispose()


# ---- Section (Sheet "1") --------------------------------------------------

def _import_sections(session) -> None:
    """Insert sections from Sheet '1'."""

    df = pd.read_excel(EXCEL_PATH, sheet_name="1", engine="openpyxl")
    df = df.dropna(subset=["CODE1"])

    existing_codes = {
        row.code_sec for row in session.query(Section.code_sec).all()
    }

    count = 0
    for _, row in df.iterrows():
        code = _code_str(row["CODE1"], 1)
        if code in existing_codes:
            continue

        section = Section(
            code_sec=code,
            name_sec=str(row["NAME"]).strip(),
            description_sec=_clean_text(row.get("desc")),
            tasks_sec=_clean_text(row.get("tasks")),
        )
        session.add(section)
        existing_codes.add(code)
        count += 1

    session.flush()
    log.info("Sections  – inserted %d, skipped %d", count, len(df) - count)


# ---- Subsection (Sheet "2" + parent link from Sheet "6") ------------------

def _import_subsections(session) -> None:
    """Insert subsections from Sheet '2'.

    Parent *section* is resolved via Sheet '6' which maps Code2 → Code1.
    """

    # Build code2 → code1 mapping from Sheet "6"
    df6 = pd.read_excel(EXCEL_PATH, sheet_name="6", engine="openpyxl")
    df6 = df6.dropna(subset=["Code2"])
    code2_to_code1: dict[str, str] = {}
    for _, r in df6.iterrows():
        c2 = _code_str(r["Code2"], 2)
        if c2 not in code2_to_code1:
            code2_to_code1[c2] = _code_str(r["Code1"], 1)

    # Section lookup
    sec_by_code: dict[str, int] = {
        row.code_sec: row.id_sec
        for row in session.query(Section.code_sec, Section.id_sec).all()
    }

    df2 = pd.read_excel(EXCEL_PATH, sheet_name="2", engine="openpyxl")
    df2 = df2.dropna(subset=["CODE2"])

    existing_codes = {
        row.code_sub for row in session.query(Subsection.code_sub).all()
    }

    count = 0
    for _, row in df2.iterrows():
        code = _code_str(row["CODE2"], 2)
        if code in existing_codes:
            continue

        parent_code = code2_to_code1.get(code)
        if parent_code is None or parent_code not in sec_by_code:
            log.warning("Subsection %s – parent section not found, skipped.", code)
            continue

        subsection = Subsection(
            id_sec=sec_by_code[parent_code],
            code_sub=code,
            name_sub=str(row["NAME"]).strip(),
        )
        session.add(subsection)
        existing_codes.add(code)
        count += 1

    session.flush()
    log.info("Subsections – inserted %d, skipped %d", count, len(df2) - count)


# ---- Division & Group (Sheet "6" hierarchy + Sheet "4" descriptions) ------

def _import_groups_and_divisions(session) -> None:
    """Insert divisions (from Sheet '6') and groups (from Sheets '6' + '4').

    Sheet '4' provides ``description_gr`` and ``tasks_gr`` for groups.
    """

    # --- Sheet "4": group names, descriptions & tasks keyed by code --------
    df4 = pd.read_excel(EXCEL_PATH, sheet_name="4", engine="openpyxl")
    df4 = df4.dropna(subset=["CODE4"])
    group_meta: dict[str, dict] = {}
    for _, r in df4.iterrows():
        c4 = _code_str(r["CODE4"], 4)
        group_meta[c4] = {
            "name": _clean_text(r.get("NAME")),
            "description_gr": _clean_text(r.get("desc")),
            "tasks_gr": _clean_text(r.get("tasks")),
        }

    # --- Sheet "6": hierarchy ----------------------------------------------
    df6 = pd.read_excel(EXCEL_PATH, sheet_name="6", engine="openpyxl")
    df6 = df6.dropna(subset=["Code6"])

    # Subsection lookup
    sub_by_code: dict[str, int] = {
        row.code_sub: row.id_sub
        for row in session.query(Subsection.code_sub, Subsection.id_sub).all()
    }

    # -- Divisions ----------------------------------------------------------
    existing_div_codes = {
        row.code_div for row in session.query(Division.code_div).all()
    }
    div_by_code: dict[str, int] = {
        row.code_div: row.id_div
        for row in session.query(Division.code_div, Division.id_div).all()
    }

    seen_div: dict[str, dict] = {}
    for _, r in df6.iterrows():
        c3 = _code_str(r["Code3"], 3)
        if c3 not in seen_div:
            seen_div[c3] = {
                "name": str(r["Desc3"]).strip(),
                "parent_sub": _code_str(r["Code2"], 2),
            }

    div_count = 0
    for code, info in seen_div.items():
        if code in existing_div_codes:
            continue
        parent_id = sub_by_code.get(info["parent_sub"])
        if parent_id is None:
            log.warning("Division %s – parent subsection %s not found, skipped.",
                        code, info["parent_sub"])
            continue

        division = Division(
            id_sub=parent_id,
            code_div=code,
            name_div=info["name"],
        )
        session.add(division)
        session.flush()
        div_by_code[code] = division.id_div
        existing_div_codes.add(code)
        div_count += 1

    log.info("Divisions – inserted %d, skipped %d",
             div_count, len(seen_div) - div_count)

    # -- Groups -------------------------------------------------------------
    existing_gr_codes = {
        row.code_gr for row in session.query(Group.code_gr).all()
    }
    gr_by_code: dict[str, int] = {
        row.code_gr: row.id_gr
        for row in session.query(Group.code_gr, Group.id_gr).all()
    }

    seen_gr: dict[str, dict] = {}
    for _, r in df6.iterrows():
        c4 = _code_str(r["Code4"], 4)
        if c4 not in seen_gr:
            seen_gr[c4] = {
                "name": str(r["Desc4"]).strip() if pd.notna(r["Desc4"]) else None,
                "parent_div": _code_str(r["Code3"], 3),
            }

    gr_count = 0
    for code, info in seen_gr.items():
        if code in existing_gr_codes:
            continue
        parent_id = div_by_code.get(info["parent_div"])
        if parent_id is None:
            log.warning("Group %s – parent division %s not found, skipped.",
                        code, info["parent_div"])
            continue

        meta = group_meta.get(code, {})

        # Resolve group name: Sheet "6" Desc4 → Sheet "4" NAME → fallback
        group_name = info["name"] or meta.get("name") or f"مجموعة {code}"
        if group_name == f"مجموعة {code}":
            log.warning("Group %s – name missing in both sheets, using fallback.", code)

        group = Group(
            id_div=parent_id,
            code_gr=code,
            name_gr=group_name,
            description_gr=meta.get("description_gr"),
            tasks_gr=meta.get("tasks_gr"),
        )
        session.add(group)
        session.flush()
        gr_by_code[code] = group.id_gr
        existing_gr_codes.add(code)
        gr_count += 1

    log.info("Groups    – inserted %d, skipped %d",
             gr_count, len(seen_gr) - gr_count)


# ---- Occupation (Sheet "6") -----------------------------------------------

def _import_occupations(session) -> None:
    """Insert occupations from Sheet '6'."""

    df6 = pd.read_excel(EXCEL_PATH, sheet_name="6", engine="openpyxl")
    df6 = df6.dropna(subset=["Code6"])

    gr_by_code: dict[str, int] = {
        row.code_gr: row.id_gr
        for row in session.query(Group.code_gr, Group.id_gr).all()
    }

    existing_codes = {
        row.code_oc for row in session.query(Occupation.code_oc).all()
    }

    count = 0
    for _, row in df6.iterrows():
        code = _code_str(row["Code6"], 6)
        if code in existing_codes:
            continue

        parent_code = _code_str(row["Code4"], 4)
        parent_id = gr_by_code.get(parent_code)
        if parent_id is None:
            log.warning("Occupation %s – parent group %s not found, skipped.",
                        code, parent_code)
            continue

        occupation = Occupation(
            id_gr=parent_id,
            code_oc=code,
            name_oc=str(row["Desc6"]).strip(),
        )
        session.add(occupation)
        existing_codes.add(code)
        count += 1

    session.flush()
    log.info("Occupations – inserted %d, skipped %d",
             count, len(df6) - count)


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import_data()
