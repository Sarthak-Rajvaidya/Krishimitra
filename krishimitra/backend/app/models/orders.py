import enum
from datetime import datetime

from sqlalchemy import (Boolean, CheckConstraint, DateTime, Enum, ForeignKey, Integer, String, Text,
                        UniqueConstraint, JSON)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Cart(Base, TimestampMixin):
    __tablename__ = "carts"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    items: Mapped[list["CartItem"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class CartItem(Base):
    __tablename__ = "cart_items"
    __table_args__ = (UniqueConstraint("cart_id", "product_id"), CheckConstraint("quantity > 0"))
    id: Mapped[int] = mapped_column(primary_key=True)
    cart_id: Mapped[int] = mapped_column(ForeignKey("carts.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    recommendation_id: Mapped[int | None] = mapped_column(ForeignKey("recommendations.id"))
    product: Mapped["Product"] = relationship(lazy="joined")  # noqa: F821


class OrderStatus(str, enum.Enum):
    PLACED = "PLACED"
    CONFIRMED = "CONFIRMED"              # accepted by the supplier
    PACKED = "PACKED"
    READY_FOR_DISPATCH = "READY_FOR_DISPATCH"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    REJECTED = "REJECTED"                # supplier declined
    CANCELLED = "CANCELLED"
    RETURN_REQUESTED = "RETURN_REQUESTED"
    RETURNED = "RETURNED"
    REFUNDED = "REFUNDED"


class PaymentMode(str, enum.Enum):
    COD = "COD"
    SIMULATED_ONLINE = "SIMULATED_ONLINE"
    WALLET = "WALLET"
    ONLINE = "ONLINE"


class Order(Base, TimestampMixin):
    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    order_number: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(80))
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)   # seller for this (sub-)order
    checkout_group: Mapped[str | None] = mapped_column(String(32), index=True)           # links the split orders of one checkout
    district_id: Mapped[int | None] = mapped_column(ForeignKey("districts.id"), index=True)
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus), default=OrderStatus.PLACED, index=True)
    payment_mode: Mapped[PaymentMode] = mapped_column(Enum(PaymentMode))
    subtotal_paise: Mapped[int] = mapped_column(Integer)   # tax-inclusive item total before discount
    discount_paise: Mapped[int] = mapped_column(Integer, default=0)
    delivery_fee_paise: Mapped[int] = mapped_column(Integer, default=0)
    total_paise: Mapped[int] = mapped_column(Integer)
    tax_paise: Mapped[int] = mapped_column(Integer, default=0)  # GST contained in item prices (after discount)
    promo_code: Mapped[str | None] = mapped_column(String(40))
    ship_name: Mapped[str] = mapped_column(String(160))
    ship_phone: Mapped[str | None] = mapped_column(String(20))
    ship_line1: Mapped[str] = mapped_column(String(255))
    ship_district: Mapped[str] = mapped_column(String(120), index=True)
    ship_state: Mapped[str] = mapped_column(String(80))
    ship_pincode: Mapped[str] = mapped_column(String(6))
    location_id: Mapped[int] = mapped_column(ForeignKey("inventory_locations.id"))
    advisory_ref: Mapped[dict | None] = mapped_column(JSON)  # stored only with farmer's consent
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    items: Mapped[list["OrderItem"]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    history: Mapped[list["OrderStatusHistory"]] = relationship(cascade="all, delete-orphan", lazy="selectin",
                                                               order_by="OrderStatusHistory.id")


class OrderItem(Base):
    __tablename__ = "order_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    name_snapshot: Mapped[str] = mapped_column(String(200))
    sku_snapshot: Mapped[str] = mapped_column(String(40))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price_paise: Mapped[int] = mapped_column(Integer)
    unit_cost_paise: Mapped[int] = mapped_column(Integer, default=0)
    gst_rate_bp: Mapped[int] = mapped_column(Integer, default=0)
    line_total_paise: Mapped[int] = mapped_column(Integer)


class OrderStatusHistory(Base):
    __tablename__ = "order_status_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus))
    note: Mapped[str | None] = mapped_column(String(255))
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PaymentStatus(str, enum.Enum):
    PENDING = "PENDING"            # COD awaiting collection
    SIMULATED_PAID = "SIMULATED_PAID"
    COLLECTED = "COLLECTED"
    FAILED = "FAILED"


class PaymentRecord(Base, TimestampMixin):
    __tablename__ = "payment_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    mode: Mapped[PaymentMode] = mapped_column(Enum(PaymentMode))
    status: Mapped[PaymentStatus] = mapped_column(Enum(PaymentStatus))
    amount_paise: Mapped[int] = mapped_column(Integer)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    reconciled: Mapped[bool] = mapped_column(Boolean, default=False)


class RefundRecord(Base, TimestampMixin):
    __tablename__ = "refund_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    amount_paise: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(255), default="")
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
