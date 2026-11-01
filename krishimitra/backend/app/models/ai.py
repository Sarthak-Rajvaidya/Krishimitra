import enum
from datetime import datetime

from sqlalchemy import (Boolean, DateTime, Enum, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class ModelVersion(Base, TimestampMixin):
    __tablename__ = "model_versions"
    __table_args__ = (UniqueConstraint("name", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    version: Mapped[str] = mapped_column(String(40))
    architecture: Mapped[str] = mapped_column(String(80), default="mobilenet_v3_small")
    artifact_path: Mapped[str | None] = mapped_column(String(255))
    classes: Mapped[list | None] = mapped_column(JSON)
    dataset_note: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    is_trained: Mapped[bool] = mapped_column(Boolean, default=False)


class ModelEvaluation(Base):
    __tablename__ = "model_evaluations"
    id: Mapped[int] = mapped_column(primary_key=True)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id"), index=True)
    test_accuracy: Mapped[float] = mapped_column(Float)
    metrics: Mapped[dict] = mapped_column(JSON)  # per-class P/R/F1 + confusion matrix
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DiagnosisStatus(str, enum.Enum):
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    PREDICTED = "PREDICTED"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"


class ExpertReviewStatus(str, enum.Enum):
    NOT_REQUESTED = "NOT_REQUESTED"
    REQUESTED = "REQUESTED"
    REVIEWED = "REVIEWED"


class CropDiagnosis(Base, TimestampMixin):
    __tablename__ = "crop_diagnoses"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    image_key: Mapped[str] = mapped_column(String(120))  # opaque storage key, never a filesystem path
    crop: Mapped[str | None] = mapped_column(String(80))
    crop_stage: Mapped[str | None] = mapped_column(String(80))
    plant_part: Mapped[str | None] = mapped_column(String(80))
    symptoms: Mapped[str | None] = mapped_column(Text)
    district: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[DiagnosisStatus] = mapped_column(Enum(DiagnosisStatus))
    model_version_id: Mapped[int | None] = mapped_column(ForeignKey("model_versions.id"))
    user_agrees: Mapped[bool | None] = mapped_column(Boolean)
    expert_review: Mapped[ExpertReviewStatus] = mapped_column(Enum(ExpertReviewStatus), default=ExpertReviewStatus.NOT_REQUESTED)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    predictions: Mapped[list["DiagnosisPrediction"]] = relationship(cascade="all, delete-orphan", lazy="selectin",
                                                                    order_by="DiagnosisPrediction.rank")
    followups: Mapped[list["DiagnosisFollowup"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class DiagnosisPrediction(Base):
    __tablename__ = "diagnosis_predictions"
    id: Mapped[int] = mapped_column(primary_key=True)
    diagnosis_id: Mapped[int] = mapped_column(ForeignKey("crop_diagnoses.id", ondelete="CASCADE"), index=True)
    rank: Mapped[int] = mapped_column(Integer)
    class_label: Mapped[str] = mapped_column(String(120))
    probability: Mapped[float] = mapped_column(Float)  # raw softmax output, NOT a calibrated diagnosis probability


class DiagnosisFollowup(Base):
    __tablename__ = "diagnosis_followups"
    id: Mapped[int] = mapped_column(primary_key=True)
    diagnosis_id: Mapped[int] = mapped_column(ForeignKey("crop_diagnoses.id", ondelete="CASCADE"), index=True)
    note: Mapped[str] = mapped_column(Text)
    outcome: Mapped[str | None] = mapped_column(String(40))  # improved | same | worse
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AdvisoryConversation(Base, TimestampMixin):
    __tablename__ = "advisory_conversations"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(160), default="New conversation")
    diagnosis_id: Mapped[int | None] = mapped_column(ForeignKey("crop_diagnoses.id"))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    messages: Mapped[list["AdvisoryMessage"]] = relationship(cascade="all, delete-orphan", lazy="selectin",
                                                             order_by="AdvisoryMessage.id")


class AdvisoryMessage(Base):
    __tablename__ = "advisory_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("advisory_conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(12))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    citations: Mapped[list | None] = mapped_column(JSON)
    provider: Mapped[str | None] = mapped_column(String(20))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    grounded: Mapped[bool | None] = mapped_column(Boolean)
    feedback: Mapped[int | None] = mapped_column(Integer)  # 1 useful, -1 not useful
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LLMCallLog(Base):
    """Observability only: provider, latency, outcome. No prompts or keys stored."""
    __tablename__ = "llm_call_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(20), index=True)
    ok: Mapped[bool] = mapped_column(Boolean)
    latency_ms: Mapped[int] = mapped_column(Integer)
    error_kind: Mapped[str | None] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class DocStatus(str, enum.Enum):
    PENDING = "PENDING"
    INDEXED = "INDEXED"
    FAILED = "FAILED"


class KnowledgeDocument(Base, TimestampMixin):
    __tablename__ = "knowledge_documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    source_org: Mapped[str] = mapped_column(String(160))
    source_url: Mapped[str | None] = mapped_column(String(500))
    licence: Mapped[str] = mapped_column(String(160))           # provenance/licence is mandatory
    authorized_by: Mapped[str] = mapped_column(String(160))
    storage_key: Mapped[str] = mapped_column(String(120))
    file_type: Mapped[str] = mapped_column(String(10))
    language: Mapped[str] = mapped_column(String(5), default="en")
    status: Mapped[DocStatus] = mapped_column(Enum(DocStatus), default=DocStatus.PENDING)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    chunks: Mapped[list["KnowledgeChunk"]] = relationship(cascade="all, delete-orphan", lazy="noload")


class KnowledgeChunk(Base):
    """Metadata only. Vector + text payload live in Qdrant; text preview kept for audit."""
    __tablename__ = "knowledge_chunks"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    page: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(160))
    qdrant_point_id: Mapped[str] = mapped_column(String(64), unique=True)
    preview: Mapped[str] = mapped_column(String(300))


class IngestionJob(Base, TimestampMixin):
    __tablename__ = "ingestion_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("knowledge_documents.id"), index=True)
    status: Mapped[DocStatus] = mapped_column(Enum(DocStatus), default=DocStatus.PENDING)
    error: Mapped[str | None] = mapped_column(String(500))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    triggered_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class Recommendation(Base):
    __tablename__ = "recommendations"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    diagnosis_id: Mapped[int | None] = mapped_column(ForeignKey("crop_diagnoses.id"), index=True)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("advisory_conversations.id"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    purpose: Mapped[str] = mapped_column(String(200))
    included: Mapped[bool] = mapped_column(Boolean)
    reasoning: Mapped[dict] = mapped_column(JSON)  # evidence, citations, uncertainty, restrictions, why included/excluded
    requires_expert: Mapped[bool] = mapped_column(Boolean, default=True)
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    added_to_cart_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RecommendationFeedback(Base):
    __tablename__ = "recommendation_feedback"
    id: Mapped[int] = mapped_column(primary_key=True)
    recommendation_id: Mapped[int] = mapped_column(ForeignKey("recommendations.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    helpful: Mapped[bool] = mapped_column(Boolean)
    outcome: Mapped[str | None] = mapped_column(String(40))
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
