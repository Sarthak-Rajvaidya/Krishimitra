import enum
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Enum, Float, ForeignKey, Integer, JSON, String, Table, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class RoleName(str, enum.Enum):
    FARMER = "FARMER"
    EXPERT = "EXPERT"
    SUPPLIER = "SUPPLIER"
    DELIVERY = "DELIVERY"
    SOIL_CENTER = "SOIL_CENTER"
    DISTRICT_MANAGER = "DISTRICT_MANAGER"
    ADMIN = "ADMIN"
    SUPER_ADMIN = "SUPER_ADMIN"
    # Business staff roles kept from the first prototype
    FINANCE = "FINANCE"
    DEVELOPER = "DEVELOPER"
    FOUNDER = "FOUNDER"


class UserStatus(str, enum.Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"   # contact not verified yet
    PENDING_APPROVAL = "PENDING_APPROVAL"           # waiting for admin (experts, suppliers, delivery, soil centres)
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    BLOCKED = "BLOCKED"
    REJECTED = "REJECTED"
    DELETED = "DELETED"


role_permissions = Table(
    "role_permissions", Base.metadata,
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)


class Permission(Base):
    __tablename__ = "permissions"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    description: Mapped[str] = mapped_column(String(255), default="")


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[RoleName] = mapped_column(Enum(RoleName), unique=True)
    permissions: Mapped[list[Permission]] = relationship(secondary=role_permissions, lazy="selectin")


class District(Base, TimestampMixin):
    __tablename__ = "districts"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    state: Mapped[str] = mapped_column(String(80))
    code: Mapped[str] = mapped_column(String(20), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")      # PLANNED | ACTIVE | PAUSED (expansion management)
    target_launch: Mapped[str | None] = mapped_column(String(20))
    franchise_id: Mapped[int | None] = mapped_column(ForeignKey("franchises.id"))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("name", "state"),)


class Franchise(Base, TimestampMixin):
    __tablename__ = "franchises"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    owner_name: Mapped[str] = mapped_column(String(160))
    contact: Mapped[str | None] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    terms_note: Mapped[str | None] = mapped_column(String(500))


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, index=True, nullable=True)   # mobile number, digits only
    full_name: Mapped[str] = mapped_column(String(160))
    password_hash: Mapped[str] = mapped_column(String(255))
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), index=True)
    status: Mapped[UserStatus] = mapped_column(Enum(UserStatus), default=UserStatus.PENDING_VERIFICATION, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)       # always == (status is ACTIVE or PENDING_APPROVAL); see services/accounts.py
    mobile_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    district_id: Mapped[int | None] = mapped_column(ForeignKey("districts.id"), index=True)
    language: Mapped[str] = mapped_column(String(5), default="en")
    photo_key: Mapped[str | None] = mapped_column(String(120))
    status_note: Mapped[str | None] = mapped_column(String(300))
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    privacy: Mapped[dict | None] = mapped_column(JSON)          # {"community_profile_public": bool, "share_with_experts": bool}
    notif_prefs: Mapped[dict | None] = mapped_column(JSON)      # {"in_app": true, "sms": true, "email": false, "push": false, "muted_kinds": []}
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    role: Mapped[Role] = relationship(lazy="joined")
    profile: Mapped["FarmerProfile | None"] = relationship(back_populates="user", uselist=False)


class FarmerProfile(Base, TimestampMixin):
    __tablename__ = "farmer_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    village: Mapped[str | None] = mapped_column(String(120))
    district: Mapped[str | None] = mapped_column(String(120), index=True)
    state: Mapped[str | None] = mapped_column(String(80))
    primary_crops: Mapped[str | None] = mapped_column(String(255))
    farm_size_acres: Mapped[float | None] = mapped_column()
    land_ownership: Mapped[str | None] = mapped_column(String(30))     # OWNED | LEASED | SHARED
    experience_years: Mapped[int | None] = mapped_column(Integer)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    user: Mapped[User] = relationship(back_populates="profile")


class Address(Base, TimestampMixin):
    __tablename__ = "addresses"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    label: Mapped[str] = mapped_column(String(40), default="Home")
    line1: Mapped[str] = mapped_column(String(255))
    village: Mapped[str | None] = mapped_column(String(120))
    district: Mapped[str] = mapped_column(String(120))
    state: Mapped[str] = mapped_column(String(80))
    pincode: Mapped[str] = mapped_column(String(6), index=True)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class ServiceablePincode(Base):
    """Delivery areas. Managed by admins / district managers."""
    __tablename__ = "serviceable_pincodes"
    __table_args__ = (UniqueConstraint("pincode", "location_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    pincode: Mapped[str] = mapped_column(String(6), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("inventory_locations.id"))
    district_id: Mapped[int | None] = mapped_column(ForeignKey("districts.id"), index=True)
    delivery_fee_paise: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
