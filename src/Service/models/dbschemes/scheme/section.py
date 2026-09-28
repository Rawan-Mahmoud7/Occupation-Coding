from .oc_coding_base import SQLAlchemyBase
from sqlalchemy import Column, Integer, String, CheckConstraint
from sqlalchemy.orm import relationship

class Section(SQLAlchemyBase):

    __tablename__ = "sections"

    id_sec = Column(Integer, primary_key=True, autoincrement=True)
    code_sec = Column(String(1), nullable=False, unique=True)
    name_sec = Column(String(255), nullable=False, unique=True)

    subsections = relationship("Subsection", back_populates="section", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint(
            "code_sec ~ '^[0-9]$'",
            name="ck_sections_code_format"
        ),
    )