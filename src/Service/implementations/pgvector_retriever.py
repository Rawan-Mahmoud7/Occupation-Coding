"""
Pgvector Retriever Implementation.
Searches occupation_vectors using weighted cosine similarity across all 4
context-aware chunk vectors (v_identity, v_hierarchy, v_chapter, v_main),
strictly filtered to eligible ISCO sections, and retrieves full hierarchy names.

Scoring formula (matches the Colab voyage-context-4 evaluation script):
  score = 0.55 * cosine(q, v_identity)
        + 0.15 * cosine(q, v_hierarchy)
        + 0.18 * cosine(q, v_chapter)
        + 0.12 * cosine(q, v_main)
"""

from typing import List, Optional
from sqlalchemy import text
from Service.interfaces.pipeline_context import Candidate
from Service.models.dbschemes.scheme.occupation import Occupation
from Service.models.dbschemes.scheme.occupation_vector import OccupationVector

# Chunk weights – must match import_vectors.py and the Colab script exactly
_W_IDENTITY  = 0.55
_W_HIERARCHY = 0.15
_W_CHAPTER   = 0.18
_W_MAIN      = 0.12


class PgvectorRetriever:
    """
    Implements Retriever protocol.
    Searches PostgreSQL pgvector occupation_vectors table.
    """

    def __init__(self, db_session_factory):
        self._session_factory = db_session_factory

    async def search(
        self,
        query_vector: List[float],
        eligible_sections: List[int],
        top_k: int = 20
    ) -> List[Candidate]:
        """
        Executes pgvector weighted-chunk cosine similarity search filtered to
        eligible sections.  Computes the weighted sum of cosine similarities
        between the query vector and each of the 4 context-aware chunk vectors
        stored per occupation (matching the Colab scoring formula).
        Returns candidates populated with code, name, and full hierarchy names.
        """
        if not query_vector:
            return []

        # Convert vector to string representation for pgvector
        vec_str = "[" + ",".join(str(float(x)) for x in query_vector) + "]"
        sections_list = [int(s) for s in eligible_sections] if eligible_sections else [1, 2, 3, 4, 5, 6, 7, 8, 9]

        query = text("""
            SELECT 
                oc.code_oc,
                oc.name_oc,
                CAST(sec.code_sec AS INTEGER) AS section_code,
                sec.name_sec,
                sub.name_sub,
                div.name_div,
                gr.name_gr,
                (
                    :w_identity  * (1 - (ov.v_identity  <=> :query_vec))
                  + :w_hierarchy * (1 - (ov.v_hierarchy <=> :query_vec))
                  + :w_chapter   * (1 - (ov.v_chapter   <=> :query_vec))
                  + :w_main      * (1 - (ov.v_main      <=> :query_vec))
                ) AS similarity
            FROM occupation_vectors ov
            JOIN occupations oc ON ov.id_oc = oc.id_oc
            JOIN groups gr ON oc.id_gr = gr.id_gr
            JOIN divisions div ON gr.id_div = div.id_div
            JOIN subsections sub ON div.id_sub = sub.id_sub
            JOIN sections sec ON sub.id_sec = sec.id_sec
            WHERE CAST(sec.code_sec AS INTEGER) = ANY(:eligible_sections)
            ORDER BY similarity DESC
            LIMIT :top_k;
        """)

        async with self._session_factory() as session:
            result = await session.execute(
                query,
                {
                    "query_vec": vec_str,
                    "eligible_sections": sections_list,
                    "top_k": top_k,
                    "w_identity": _W_IDENTITY,
                    "w_hierarchy": _W_HIERARCHY,
                    "w_chapter": _W_CHAPTER,
                    "w_main": _W_MAIN,
                }
            )
            rows = result.fetchall()

            candidates = []
            for row in rows:
                candidates.append(
                    Candidate(
                        code=row.code_oc,
                        name=row.name_oc,
                        similarity=float(row.similarity),
                        section_name=row.name_sec or "",
                        section_code=int(row.section_code or 0),
                        subsection_name=row.name_sub or "",
                        division_name=row.name_div or "",
                        group_name=row.name_gr or "",
                    )
                )

            return candidates

    async def get_by_code(self, code: str) -> Optional[Candidate]:
        """Retrieves single occupation with complete hierarchy by official code."""
        query = text("""
            SELECT 
                oc.code_oc,
                oc.name_oc,
                CAST(sec.code_sec AS INTEGER) AS section_code,
                sec.name_sec,
                sub.name_sub,
                div.name_div,
                gr.name_gr
            FROM occupations oc
            JOIN groups gr ON oc.id_gr = gr.id_gr
            JOIN divisions div ON gr.id_div = div.id_div
            JOIN subsections sub ON div.id_sub = sub.id_sub
            JOIN sections sec ON sub.id_sec = sec.id_sec
            WHERE oc.code_oc = :code
            LIMIT 1;
        """)

        async with self._session_factory() as session:
            result = await session.execute(query, {"code": code})
            row = result.first()
            if not row:
                return None

            return Candidate(
                code=row.code_oc,
                name=row.name_oc,
                similarity=1.0,
                section_name=row.name_sec or "",
                section_code=int(row.section_code or 0),
                subsection_name=row.name_sub or "",
                division_name=row.name_div or "",
                group_name=row.name_gr or "",
            )
