"""Notifications, experts' appointments, community, content (CMS), support, advisories, settings."""
import enum
from datetime import date, datetime

from sqlalchemy import (Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notif_user_read_created", "user_id", "read_at", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)       # ORDER | DELIVERY | PAYMENT | APPOINTMENT | EXPERT | DISEASE | WEATHER | IRRIGATION | IOT | ADVISORY | ACCOUNT | SCHEME | SYSTEM | STOCK
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(String(500), default="")
    data: Mapped[dict | None] = mapped_column(JSON)
    dedupe_key: Mapped[str | None] = mapped_column(String(80), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotificationOutbox(Base):
    """External deliveries (SMS / email / push) processed by the worker, so API requests never wait on third parties."""
    __tablename__ = "notification_outbox"
    id: Mapped[int] = mapped_column(primary_key=True)
    notification_id: Mapped[int | None] = mapped_column(ForeignKey("notifications.id", ondelete="SET NULL"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    channel: Mapped[str] = mapped_column(String(8))                 # SMS | EMAIL | PUSH
    target: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(160), default="")
    body: Mapped[str] = mapped_column(String(600))
    status: Mapped[str] = mapped_column(String(8), default="PENDING", index=True)   # PENDING | SENT | FAILED
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Appointment(Base, TimestampMixin):
    __tablename__ = "appointments"
    id: Mapped[int] = mapped_column(primary_key=True)
    farmer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    expert_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    mode: Mapped[str] = mapped_column(String(8))                    # CHAT | AUDIO | VIDEO | VISIT
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    topic: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(12), default="REQUESTED", index=True)   # REQUESTED | CONFIRMED | DECLINED | CANCELLED | COMPLETED | NO_SHOW
    fee_paise: Mapped[int] = mapped_column(Integer, default=0)
    paid: Mapped[bool] = mapped_column(Boolean, default=False)
    diagnosis_id: Mapped[int | None] = mapped_column(ForeignKey("crop_diagnoses.id"))
    crop_id: Mapped[int | None] = mapped_column(ForeignKey("crops.id"))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("appointments.id"))      # follow-up consultation
    meeting_url: Mapped[str | None] = mapped_column(String(300))                       # set by expert (any video provider link)
    expert_notes: Mapped[str | None] = mapped_column(Text)                             # advice / recommendations
    recommended_product_ids: Mapped[list | None] = mapped_column(JSON)                # expert recommends treatment -> marketplace
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class ConsultMessage(Base):
    __tablename__ = "consult_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id", ondelete="CASCADE"), index=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(String(2000))
    attachment_key: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class CommunityGroup(Base, TimestampMixin):
    __tablename__ = "community_groups"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    topic: Mapped[str | None] = mapped_column(String(60))
    description: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class GroupMember(Base):
    __tablename__ = "group_members"
    __table_args__ = (UniqueConstraint("group_id", "user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("community_groups.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)


class Post(Base, TimestampMixin):
    __tablename__ = "posts"
    __table_args__ = (Index("ix_posts_status_created", "status", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("community_groups.id"), index=True)
    kind: Mapped[str] = mapped_column(String(14), default="POST")      # POST | QUESTION | EXPERIENCE | SUCCESS_STORY | ANNOUNCEMENT
    title: Mapped[str | None] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    media_keys: Mapped[list | None] = mapped_column(JSON)               # [{"key":..., "type":"image|video"}]
    topic: Mapped[str | None] = mapped_column(String(60), index=True)
    status: Mapped[str] = mapped_column(String(10), default="PUBLISHED", index=True)  # PUBLISHED | HIDDEN | REMOVED
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    comment_count: Mapped[int] = mapped_column(Integer, default=0)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class Comment(Base, TimestampMixin):
    __tablename__ = "comments"
    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("comments.id"))      # reply
    body: Mapped[str] = mapped_column(String(2000))
    is_answer: Mapped[bool] = mapped_column(Boolean, default=False)               # accepted answer for QUESTION posts
    status: Mapped[str] = mapped_column(String(10), default="PUBLISHED")


class PostLike(Base):
    __tablename__ = "post_likes"
    __table_args__ = (UniqueConstraint("post_id", "user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))


class ContentReport(Base, TimestampMixin):
    __tablename__ = "content_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    target_type: Mapped[str] = mapped_column(String(10))     # POST | COMMENT
    target_id: Mapped[int] = mapped_column(Integer, index=True)
    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(10), default="OPEN", index=True)   # OPEN | ACTIONED | DISMISSED
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class Content(Base, TimestampMixin):
    """CMS: articles, guides, videos, schemes, FAQs, loan/insurance info, training, announcements."""
    __tablename__ = "content"
    __table_args__ = (Index("ix_content_kind_pub", "kind", "is_published"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(14), index=True)        # ARTICLE|GUIDE|VIDEO|TRAINING|SCHEME|FAQ|LOAN|INSURANCE|ANNOUNCEMENT|DISEASE|PEST
    category: Mapped[str | None] = mapped_column(String(60), index=True)    # crop / topic / scheme category
    title: Mapped[str] = mapped_column(String(240))
    summary: Mapped[str | None] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String(5), default="en", index=True)
    state: Mapped[str | None] = mapped_column(String(80), index=True)       # state-specific schemes; null = central / all
    level: Mapped[str | None] = mapped_column(String(10))                   # CENTRAL | STATE (schemes)
    url: Mapped[str | None] = mapped_column(String(400))                    # video link or official portal
    eligibility: Mapped[str | None] = mapped_column(Text)
    documents_required: Mapped[str | None] = mapped_column(Text)
    procedure: Mapped[str | None] = mapped_column(Text)
    benefits: Mapped[str | None] = mapped_column(Text)
    deadline: Mapped[date | None] = mapped_column(Date)
    needs_verification: Mapped[bool] = mapped_column(Boolean, default=True)  # admin flips after checking against the official source
    source: Mapped[str | None] = mapped_column(String(200))
    meta: Mapped[dict | None] = mapped_column(JSON)                          # e.g. for DISEASE: {"class_label": "...", "symptoms": "...", "prevention": "...", "organic": "..."}
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class SavedContent(Base):
    __tablename__ = "saved_content"
    __table_args__ = (UniqueConstraint("user_id", "content_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    content_id: Mapped[int] = mapped_column(ForeignKey("content.id", ondelete="CASCADE"))


class SchemeApplication(Base, TimestampMixin):
    """Farmer's own tracking of a scheme application (status is self-reported unless a connector is added)."""
    __tablename__ = "scheme_applications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    content_id: Mapped[int] = mapped_column(ForeignKey("content.id"))
    status: Mapped[str] = mapped_column(String(14), default="PLANNED")   # PLANNED | APPLIED | APPROVED | REJECTED
    reference_no: Mapped[str | None] = mapped_column(String(80))
    note: Mapped[str | None] = mapped_column(String(300))


class Ticket(Base, TimestampMixin):
    __tablename__ = "tickets"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    district_id: Mapped[int | None] = mapped_column(ForeignKey("districts.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10), default="TICKET")           # TICKET | COMPLAINT | FEEDBACK
    category: Mapped[str] = mapped_column(String(30), index=True)             # ORDER | DELIVERY | PAYMENT | SUPPLIER | EXPERT | MACHINE | APP | IOT | OTHER
    subject: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(12), default="OPEN", index=True)   # OPEN | ASSIGNED | IN_PROGRESS | RESOLVED | CLOSED
    priority: Mapped[str] = mapped_column(String(8), default="NORMAL")
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    related_type: Mapped[str | None] = mapped_column(String(20))
    related_id: Mapped[int | None] = mapped_column(Integer)
    resolution: Mapped[str | None] = mapped_column(String(500))


class TicketMessage(Base):
    __tablename__ = "ticket_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Advisory(Base):
    """Personalised advisory items produced by the rule engine (or written by an expert)."""
    __tablename__ = "advisories"
    __table_args__ = (UniqueConstraint("user_id", "dedupe_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    farm_id: Mapped[int | None] = mapped_column(ForeignKey("farms.id"), index=True)
    field_id: Mapped[int | None] = mapped_column(ForeignKey("fields.id"))
    crop_id: Mapped[int | None] = mapped_column(ForeignKey("crops.id"), index=True)
    category: Mapped[str] = mapped_column(String(20), index=True)      # IRRIGATION|WEATHER|FERTILIZER|DISEASE|HARVEST|SOIL|CROP|PEST|ORGANIC|WATER
    severity: Mapped[str] = mapped_column(String(8), default="INFO")   # INFO | WATCH | ACTION
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict | None] = mapped_column(JSON)                # inputs used, so every advisory is explainable
    source: Mapped[str] = mapped_column(String(10), default="RULE")    # RULE | EXPERT | AI
    dedupe_key: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ShareLink(Base):
    __tablename__ = "share_links"
    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    target_type: Mapped[str] = mapped_column(String(12))               # DIAGNOSIS
    target_id: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class PlatformSetting(Base):
    __tablename__ = "platform_settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict | None] = mapped_column(JSON)   # any JSON value
    description: Mapped[str | None] = mapped_column(String(200))
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
