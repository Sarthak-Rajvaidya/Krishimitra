"""Marketplace extras: wishlist, ratings, inquiries, machinery, delivery, returns, wallet, payments."""
import enum
from datetime import datetime

from sqlalchemy import (Boolean, DateTime, Enum, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint,
                        CheckConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Wishlist(Base):
    __tablename__ = "wishlist"
    __table_args__ = (UniqueConstraint("user_id", "product_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Rating(Base, TimestampMixin):
    """Generic ratings and reviews for PRODUCT | SUPPLIER | EXPERT | MACHINE | DELIVERY | SERVICE."""
    __tablename__ = "ratings"
    __table_args__ = (UniqueConstraint("user_id", "target_type", "target_id", "ref_id"),
                      CheckConstraint("rating between 1 and 5"))
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    target_type: Mapped[str] = mapped_column(String(20), index=True)
    target_id: Mapped[int] = mapped_column(Integer, index=True)
    ref_id: Mapped[int] = mapped_column(Integer, default=0)       # order / appointment / booking id the review is about (0 = none)
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(12), default="PUBLISHED")    # PUBLISHED | HIDDEN (moderation)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)          # reviewer actually bought/used it
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class Inquiry(Base, TimestampMixin):
    __tablename__ = "inquiries"
    id: Mapped[int] = mapped_column(primary_key=True)
    farmer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    message: Mapped[str] = mapped_column(String(600))
    reply: Mapped[str | None] = mapped_column(String(600))
    status: Mapped[str] = mapped_column(String(12), default="OPEN")


class Machine(Base, TimestampMixin):
    __tablename__ = "machines"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    category: Mapped[str] = mapped_column(String(30), index=True)    # TRACTOR | HARVESTER | ROTAVATOR | CULTIVATOR | SEED_DRILL | SPRAYER | THRESHER | JCB | PUMP | OTHER
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    specs: Mapped[dict | None] = mapped_column(JSON)
    image_keys: Mapped[list | None] = mapped_column(JSON)
    district: Mapped[str | None] = mapped_column(String(120), index=True)
    state: Mapped[str | None] = mapped_column(String(80))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    hourly_paise: Mapped[int | None] = mapped_column(Integer)
    daily_paise: Mapped[int | None] = mapped_column(Integer)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    approval_status: Mapped[str] = mapped_column(String(12), default="PENDING", index=True)    # PENDING | APPROVED | REJECTED
    rating_avg: Mapped[float] = mapped_column(Float, default=0)
    rating_count: Mapped[int] = mapped_column(Integer, default=0)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BookingStatus(str, enum.Enum):
    REQUESTED = "REQUESTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class MachineBooking(Base, TimestampMixin):
    __tablename__ = "machine_bookings"
    id: Mapped[int] = mapped_column(primary_key=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id"), index=True)
    renter_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    rate_type: Mapped[str] = mapped_column(String(8))                      # HOURLY | DAILY
    units: Mapped[int] = mapped_column(Integer)                            # hours or days
    amount_paise: Mapped[int] = mapped_column(Integer)
    status: Mapped[BookingStatus] = mapped_column(Enum(BookingStatus), default=BookingStatus.REQUESTED, index=True)
    payment_status: Mapped[str] = mapped_column(String(12), default="UNPAID")   # UNPAID | PAID | REFUNDED
    note: Mapped[str | None] = mapped_column(String(300))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class DeliveryStatus(str, enum.Enum):
    ASSIGNED = "ASSIGNED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    PICKED_UP = "PICKED_UP"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


class Delivery(Base, TimestampMixin):
    __tablename__ = "deliveries"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    partner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[DeliveryStatus] = mapped_column(Enum(DeliveryStatus), default=DeliveryStatus.ASSIGNED, index=True)
    otp_hash: Mapped[str | None] = mapped_column(String(64))
    otp_plain_for_farmer: Mapped[str | None] = mapped_column(String(8))     # shown to the farmer only; cleared once delivered
    fee_paise: Mapped[int] = mapped_column(Integer, default=0)              # partner earning for this delivery
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    picked_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_by: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    note: Mapped[str | None] = mapped_column(String(300))
    otp_attempts: Mapped[int] = mapped_column(Integer, default=0)


class ReturnRequest(Base, TimestampMixin):
    __tablename__ = "return_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    reason: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(12), default="REQUESTED")   # REQUESTED | APPROVED | REJECTED | REFUNDED
    decision_note: Mapped[str | None] = mapped_column(String(300))
    refund_paise: Mapped[int] = mapped_column(Integer, default=0)


class Wallet(Base, TimestampMixin):
    __tablename__ = "wallets"
    __table_args__ = (CheckConstraint("balance_paise >= 0", name="ck_wallet_nonneg"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    balance_paise: Mapped[int] = mapped_column(Integer, default=0)


class WalletTxn(Base):
    __tablename__ = "wallet_txns"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))        # TOPUP | ORDER_PAYMENT | REFUND | PAYOUT | RENTAL_PAYMENT | RENTAL_EARNING
    amount_paise: Mapped[int] = mapped_column(Integer)   # signed: + credit, - debit
    balance_after_paise: Mapped[int] = mapped_column(Integer)
    reference: Mapped[str | None] = mapped_column(String(80), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class GatewayOrder(Base, TimestampMixin):
    """Payment-gateway attempt (wallet top-up). status flips to PAID only after server-side signature verification."""
    __tablename__ = "gateway_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(20))
    provider_order_id: Mapped[str] = mapped_column(String(80), unique=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(80))
    amount_paise: Mapped[int] = mapped_column(Integer)
    purpose: Mapped[str] = mapped_column(String(20), default="WALLET_TOPUP")
    status: Mapped[str] = mapped_column(String(12), default="CREATED")      # CREATED | PAID | FAILED
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False)
