import enum
from datetime import datetime

from sqlalchemy import (Boolean, CheckConstraint, DateTime, Enum, Float, ForeignKey, Integer, String, Text,
                        UniqueConstraint, JSON)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class ProductCategory(Base, TimestampMixin):
    __tablename__ = "product_categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ProductType(str, enum.Enum):
    FERTILIZER = "FERTILIZER"
    ORGANIC_FERTILIZER = "ORGANIC_FERTILIZER"
    MICRONUTRIENT = "MICRONUTRIENT"
    PESTICIDE = "PESTICIDE"
    FUNGICIDE = "FUNGICIDE"
    INSECTICIDE = "INSECTICIDE"
    HERBICIDE = "HERBICIDE"
    AGRI_CHEMICAL = "AGRI_CHEMICAL"
    PLANT_PROTECTION = "PLANT_PROTECTION"
    SEED = "SEED"
    TOOL = "TOOL"
    EQUIPMENT = "EQUIPMENT"
    IRRIGATION = "IRRIGATION"            # drip systems, sprinklers
    PUMP = "PUMP"
    GREENHOUSE = "GREENHOUSE"
    ACCESSORY = "ACCESSORY"
    OTHER = "OTHER"


class Product(Base, TimestampMixin):
    __tablename__ = "products"
    __table_args__ = (CheckConstraint("price_paise >= 0"), CheckConstraint("cost_paise >= 0"))
    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("product_categories.id"), index=True)
    product_type: Mapped[ProductType] = mapped_column(Enum(ProductType))
    description: Mapped[str] = mapped_column(Text, default="")
    pack_size: Mapped[str] = mapped_column(String(40))
    unit_qty: Mapped[float] = mapped_column(default=1)      # numeric quantity in pack
    unit: Mapped[str] = mapped_column(String(10), default="kg")
    price_paise: Mapped[int] = mapped_column(Integer)       # selling price per pack, tax-inclusive
    cost_paise: Mapped[int] = mapped_column(Integer, default=0)
    gst_rate_bp: Mapped[int] = mapped_column(Integer, default=500)  # basis points (500 = 5%)
    image_url: Mapped[str | None] = mapped_column(String(500))
    crops: Mapped[str] = mapped_column(String(255), default="")      # comma separated supported crops (catalogue metadata)
    use_tags: Mapped[str] = mapped_column(String(255), default="")
    safety_info: Mapped[str] = mapped_column(Text, default="")
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)   # null = platform-owned listing
    brand: Mapped[str | None] = mapped_column(String(80), index=True)
    images: Mapped[list | None] = mapped_column(JSON)        # list of storage keys or URLs
    specs: Mapped[dict | None] = mapped_column(JSON)
    approval_status: Mapped[str] = mapped_column(String(10), default="APPROVED", index=True)   # PENDING | APPROVED | REJECTED
    approval_note: Mapped[str | None] = mapped_column(String(300))
    rating_avg: Mapped[float] = mapped_column(Float, default=0)
    rating_count: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    category: Mapped[ProductCategory] = relationship(lazy="joined")
    label: Mapped["ProductLabel | None"] = relationship(back_populates="product", uselist=False, lazy="joined")


class ProductLabel(Base, TimestampMixin):
    """Verified label / compliance metadata. Left unverified for demo products."""
    __tablename__ = "product_labels"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), unique=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    registration_ref: Mapped[str | None] = mapped_column(String(120))
    label_crops: Mapped[str | None] = mapped_column(Text)       # crops/targets stated on the verified label
    label_targets: Mapped[str | None] = mapped_column(Text)     # diseases/pests/nutrients on the label
    restrictions: Mapped[str | None] = mapped_column(Text)
    source_document_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_documents.id"))
    product: Mapped[Product] = relationship(back_populates="label")


class InventoryLocation(Base, TimestampMixin):
    __tablename__ = "inventory_locations"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)   # a supplier's own shop stock
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class InventoryBalance(Base):
    __tablename__ = "inventory_balances"
    __table_args__ = (UniqueConstraint("product_id", "location_id"),
                      CheckConstraint("on_hand >= 0", name="ck_on_hand_nonneg"),
                      CheckConstraint("reserved >= 0", name="ck_reserved_nonneg"))
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("inventory_locations.id"))
    on_hand: Mapped[int] = mapped_column(Integer, default=0)
    reserved: Mapped[int] = mapped_column(Integer, default=0)
    reorder_threshold: Mapped[int] = mapped_column(Integer, default=10)
    product: Mapped[Product] = relationship(lazy="joined")


class InvTxnType(str, enum.Enum):
    RECEIPT = "RECEIPT"
    SALE = "SALE"
    ADJUSTMENT = "ADJUSTMENT"
    RETURN = "RETURN"
    CANCEL_RESTOCK = "CANCEL_RESTOCK"


class InventoryTransaction(Base):
    __tablename__ = "inventory_transactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("inventory_locations.id"))
    txn_type: Mapped[InvTxnType] = mapped_column(Enum(InvTxnType))
    quantity_delta: Mapped[int] = mapped_column(Integer)
    reference: Mapped[str | None] = mapped_column(String(80))
    note: Mapped[str | None] = mapped_column(String(255))
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Promotion(Base, TimestampMixin):
    __tablename__ = "promotions"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    percent_off_bp: Mapped[int] = mapped_column(Integer, default=0)
    max_discount_paise: Mapped[int] = mapped_column(Integer, default=0)
    min_order_paise: Mapped[int] = mapped_column(Integer, default=0)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Review(Base, TimestampMixin):
    __tablename__ = "reviews"
    __table_args__ = (UniqueConstraint("user_id", "product_id"), CheckConstraint("rating between 1 and 5"))
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(Text, default="")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
