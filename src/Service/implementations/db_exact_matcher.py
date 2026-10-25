"""
Fast Exact Matcher Implementation.
Queries occupations table directly using single-table indexed lookup.
Extracts section code from leading digit code_oc[0] without SQL joins.
"""

from typing import Optional
from sqlalchemy.future import select
from Service.interfaces.base_matcher import MatchResult
from Service.models.dbschemes.scheme.occupation import Occupation


class DBExactMatcher:
    """Fast indexed exact matching using occupation table directly without table joins."""

    def __init__(self, db_session_factory):
        self._session_factory = db_session_factory

    async def match(self, normalized_name: str) -> Optional[MatchResult]:
        """
        Searches occupations table for an exact name match.
        Extracts major section code directly from code_oc[0].
        """
        if not normalized_name:
            return None

        async with self._session_factory() as session:
            stmt = (
                select(Occupation.code_oc, Occupation.name_oc)
                .where(Occupation.name_oc == normalized_name)
                .limit(1)
            )
            result = await session.execute(stmt)
            row = result.first()
            if not row:
                return None

            code_oc, name_oc = row[0], row[1]
            try:
                section_code = int(code_oc[0])
            except (ValueError, IndexError):
                section_code = 0

            return MatchResult(code=code_oc, name=name_oc, section_code=section_code)
