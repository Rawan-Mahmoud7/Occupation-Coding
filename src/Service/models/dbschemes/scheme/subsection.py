from .oc_coding_base import SQLAlchemyBase
from sqlalchemy import Column, Integer, String, ForeignKey, Index, CheckConstraint
from sqlalchemy.orm import relationship

class Subsection(SQLAlchemyBase):

    __tablename__ = "subsections"

    id_sub = Column(Integer, primary_key=True, autoincrement=True)
    id_sec = Column(Integer, ForeignKey("sections.id_sec"), nullable=False)
    code_sub = Column(String(2), nullable=False, unique=True)
    name_sub = Column(String(255), nullable=False, unique=True)

    section = relationship("Section", back_populates="subsections")
    divisions = relationship("Division", back_populates="subsection", cascade="all, delete-orphan")

    __table_args__ = (
        Index('ix_subsections_id_sec', id_sec),
        CheckConstraint(
            "code_sub ~ '^[0-9]{2}$'",
            name="ck_subsections_code_format"
        ),
    )
    