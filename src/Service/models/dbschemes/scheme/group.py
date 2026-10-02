from .oc_coding_base import SQLAlchemyBase
from sqlalchemy import Column, Integer, String, Text, ForeignKey, Index, CheckConstraint
from sqlalchemy.orm import relationship

class Group(SQLAlchemyBase):

    __tablename__ = "groups"

    id_gr = Column(Integer, primary_key=True, autoincrement=True)
    id_div = Column(Integer, ForeignKey("divisions.id_div"), nullable=False)
    code_gr = Column(String(4), nullable=False, unique=True)
    name_gr = Column(String(255), nullable=False, unique=True)
    description_gr = Column(Text, nullable=True)
    tasks_gr = Column(Text, nullable=True)

    division = relationship("Division", back_populates="groups")
    occupations = relationship("Occupation", back_populates="group", cascade="all, delete-orphan")

    __table_args__ = (
        Index('ix_groups_id_div', id_div),
        CheckConstraint(
            "code_gr ~ '^[0-9]{4}$'",
            name="ck_groups_code_format"
        ),
    )
