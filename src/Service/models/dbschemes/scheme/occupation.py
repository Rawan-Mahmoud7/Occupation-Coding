from .oc_coding_base import SQLAlchemyBase
from sqlalchemy import Column, Integer, String, ForeignKey, Index, CheckConstraint
from sqlalchemy.orm import relationship

class Occupation(SQLAlchemyBase):

    __tablename__ = "occupations"

    id_oc = Column(Integer, primary_key=True, autoincrement=True)
    id_gr = Column(Integer, ForeignKey("groups.id_gr"), nullable=False)
    code_oc = Column(String(6), nullable=False, unique=True)
    name_oc = Column(String(255), nullable=False, unique=True)

    group = relationship("Group", back_populates="occupations")

    __table_args__ = (
        Index('ix_occupations_id_gr', id_gr),
        CheckConstraint(
            "code_oc ~ '^[0-9]{6}$'",
            name="ck_occupations_code_format"
        ),
    )
