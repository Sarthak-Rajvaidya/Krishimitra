"""Role-specific profiles, verification documents, OTPs, password resets and sessions."""
import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ExpertProfile(Base, TimestampMixin):
    __tablename__ = "expert_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    qualification: Mapped[str] = mapped_column(String(200), default="")
    specialization: Mapped[str] = mapped_column(String(200), default="", index=True)    # comma separated tags
    experience_years: Mapped[int] = mapped_column(Integer, default=0)
    certifications: Mapped[str | None] = mapped_column(Text)
    district: Mapped[str | None] = mapped_column(String(120), index=True)
    state: Mapped[str | None] = mapped_column(String(80))
    fee_paise: Mapped[int] = mapped_column(Integer, default=0)          # per consultation
    bio: Mapped[str | None] = mapped_column(Text)
    availability: Mapped[dict | None] = mapped_column(JSON)            # {"mon": ["10:00-13:00"], ...}
    languages: Mapped[str] = mapped_column(String(80), default="en")
    modes: Mapped[str] = mapped_column(String(80), default="CHAT,AUDIO,VIDEO")
    rating_avg: Mapped[float] = mapped_column(Float, default=0)
    rating_count: Mapped[int] = mapped_column(Integer, default=0)


class SupplierProfile(Base, TimestampMixin):
    __tablename__ = "supplier_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    shop_name: Mapped[str] = mapped_column(String(200), index=True)
    owner_name: Mapped[str | None] = mapped_column(String(160))
    address: Mapped[str | None] = mapped_column(String(300))
    village: Mapped[str | None] = mapped_column(String(120))
    district: Mapped[str | None] = mapped_column(String(120), index=True)
    state: Mapped[str | None] = mapped_column(String(80))
    pincode: Mapped[str | None] = mapped_column(String(6))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    business_reg_no: Mapped[str | None] = mapped_column(String(80))
    gst_no: Mapped[str | None] = mapped_column(String(20))
    product_categories: Mapped[str | None] = mapped_column(String(255))
    bank_enc: Mapped[str | None] = mapped_column(Text)                  # Fernet-encrypted JSON {account_no, ifsc, holder}
    operating_hours: Mapped[str | None] = mapped_column(String(120))
    service_districts: Mapped[str | None] = mapped_column(String(255))  # comma separated district names
    is_open: Mapped[bool] = mapped_column(Boolean, default=True)
    rating_avg: Mapped[float] = mapped_column(Float, default=0)
    rating_count: Mapped[int] = mapped_column(Integer, default=0)


class DeliveryProfile(Base, TimestampMixin):
    __tablename__ = "delivery_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    address: Mapped[str | None] = mapped_column(String(300))
    vehicle_type: Mapped[str | None] = mapped_column(String(40))
    vehicle_number: Mapped[str | None] = mapped_column(String(20))
    licence_number: Mapped[str | None] = mapped_column(String(40))
    service_pincodes: Mapped[str | None] = mapped_column(Text)         # comma separated
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    rating_avg: Mapped[float] = mapped_column(Float, default=0)
    rating_count: Mapped[int] = mapped_column(Integer, default=0)


class SoilCenter(Base, TimestampMixin):
    __tablename__ = "soil_centers"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str | None] = mapped_column(String(300))
    district: Mapped[str | None] = mapped_column(String(120), index=True)
    state: Mapped[str | None] = mapped_column(String(80))
    pincode: Mapped[str | None] = mapped_column(String(6))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    phone: Mapped[str | None] = mapped_column(String(20))
    test_fee_paise: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class DocStatusV(str, enum.Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class UserDocument(Base, TimestampMixin):
    """Verification documents (identity, licence, GST, certificates). File bytes are encrypted at rest."""
    __tablename__ = "user_documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    doc_type: Mapped[str] = mapped_column(String(40))
    original_name: Mapped[str] = mapped_column(String(200))
    storage_key: Mapped[str] = mapped_column(String(120))
    content_type: Mapped[str] = mapped_column(String(60))
    status: Mapped[DocStatusV] = mapped_column(Enum(DocStatusV), default=DocStatusV.PENDING)
    review_note: Mapped[str | None] = mapped_column(String(300))
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class Otp(Base):
    __tablename__ = "otps"
    id: Mapped[int] = mapped_column(primary_key=True)
    target: Mapped[str] = mapped_column(String(255), index=True)       # mobile digits or lowercase email
    purpose: Mapped[str] = mapped_column(String(20))                   # VERIFY | LOGIN | RESET
    code_hash: Mapped[str] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class UserSession(Base):
    """Server-side session record so tokens can be listed and revoked."""
    __tablename__ = "user_sessions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    user_agent: Mapped[str | None] = mapped_column(String(200))
    ip: Mapped[str | None] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class DeletionRequest(Base, TimestampMixin):
    __tablename__ = "deletion_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    reason: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="PENDING")     # PENDING | DONE | REJECTED
    processed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
