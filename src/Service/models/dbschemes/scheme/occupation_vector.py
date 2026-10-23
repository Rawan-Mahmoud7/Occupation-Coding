from .oc_coding_base import SQLAlchemyBase
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, func, Index
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector

class OccupationVector(SQLAlchemyBase):

    __tablename__ = "occupation_vectors"

    id_oc = Column(Integer, ForeignKey("occupations.id_oc", ondelete="CASCADE"), primary_key=True)
    id_sec = Column(Integer, ForeignKey("sections.id_sec", ondelete="CASCADE"), nullable=False)

    v_identity = Column(Vector(1024), nullable=False)
    v_hierarchy = Column(Vector(1024), nullable=False)
    v_chapter = Column(Vector(1024), nullable=False)
    v_main = Column(Vector(1024), nullable=False)
    v_combined = Column(Vector(1024), nullable=False)

    model_name = Column(String(50), default="voyage-context-4", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    occupation = relationship("Occupation", back_populates="vector")
    section = relationship("Section", back_populates="occupation_vectors")

    __table_args__ = (
        Index("ix_occupation_vectors_id_sec", id_sec),
    )
