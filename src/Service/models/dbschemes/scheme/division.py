from .oc_coding_base import SQLAlchemyBase
from sqlalchemy import Column, Integer, String, ForeignKey, Index, CheckConstraint
from sqlalchemy.orm import relationship

class Division(SQLAlchemyBase):

    __tablename__ = "divisions"

    id_div = Column(Integer, primary_key=True, autoincrement=True)
    id_sub = Column(Integer, ForeignKey("subsections.id_sub"), nullable=False)
    code_div = Column(String(3), nullable=False, unique=True)
    name_div = Column(String(255), nullable=False, unique=True)

    subsection = relationship("Subsection", back_populates="divisions")
    groups = relationship("Group", back_populates="division", cascade="all, delete-orphan")

    __table_args__ = (
        Index('ix_divisions_id_sub', id_sub),
        CheckConstraint(
            "code_div ~ '^[0-9]{3}$'",
            name="ck_divisions_code_format"
        ),
    )
