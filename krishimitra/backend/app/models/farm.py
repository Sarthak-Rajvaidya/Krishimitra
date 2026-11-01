"""Farms, fields, crops, crop records, soil data and soil testing."""
import enum
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Farm(Base, TimestampMixin):
    __tablename__ = "farms"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    village: Mapped[str | None] = mapped_column(String(120))
    district: Mapped[str | None] = mapped_column(String(120), index=True)
    state: Mapped[str | None] = mapped_column(String(80))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    area_acres: Mapped[float | None] = mapped_column(Float)
    soil_type: Mapped[str | None] = mapped_column(String(60))
    irrigation_source: Mapped[str | None] = mapped_column(String(60))     # BOREWELL | CANAL | RAIN_FED | RIVER | DRIP ...
    boundary: Mapped[list | None] = mapped_column(JSON)                   # [[lat, lon], ...] polygon
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Field(Base, TimestampMixin):
    __tablename__ = "fields"
    id: Mapped[int] = mapped_column(primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))                        # field identification, e.g. "North plot"
    area_acres: Mapped[float | None] = mapped_column(Float)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    soil_type: Mapped[str | None] = mapped_column(String(60))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CropKnowledge(Base, TimestampMixin):
    """Reference data used by the transparent rule-based advisory. Editable by admins.
    Seeded values are generic textbook ranges, NOT local recommendations - verify with your state agriculture department."""
    __tablename__ = "crop_knowledge"
    id: Mapped[int] = mapped_column(primary_key=True)
    crop: Mapped[str] = mapped_column(String(80), unique=True)
    category: Mapped[str] = mapped_column(String(40))                     # CEREAL | PULSE | VEGETABLE | FRUIT | OILSEED | CASH
    seasons: Mapped[str] = mapped_column(String(60))                      # KHARIF,RABI,ZAID
    duration_days: Mapped[int] = mapped_column(Integer)
    ph_min: Mapped[float | None] = mapped_column(Float)
    ph_max: Mapped[float | None] = mapped_column(Float)
    soil_types: Mapped[str] = mapped_column(String(160), default="")
    water_need: Mapped[str] = mapped_column(String(10), default="MEDIUM")   # LOW | MEDIUM | HIGH
    moisture_low: Mapped[float | None] = mapped_column(Float)             # % below which irrigation is suggested
    temp_max_c: Mapped[float | None] = mapped_column(Float)               # heat stress threshold
    stages: Mapped[list | None] = mapped_column(JSON)                     # [{"name":"Germination","until_pct":15}, ...]
    notes: Mapped[str | None] = mapped_column(Text)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)


class CropStatus(str, enum.Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    HARVESTED = "HARVESTED"
    FAILED = "FAILED"


class Crop(Base, TimestampMixin):
    __tablename__ = "crops"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), index=True)
    field_id: Mapped[int | None] = mapped_column(ForeignKey("fields.id"), index=True)
    name: Mapped[str] = mapped_column(String(80), index=True)
    category: Mapped[str | None] = mapped_column(String(40))
    variety: Mapped[str | None] = mapped_column(String(80))
    season: Mapped[str | None] = mapped_column(String(20))
    area_acres: Mapped[float | None] = mapped_column(Float)
    sowing_date: Mapped[date | None] = mapped_column(Date)
    transplanting_date: Mapped[date | None] = mapped_column(Date)
    expected_harvest_date: Mapped[date | None] = mapped_column(Date)
    actual_harvest_date: Mapped[date | None] = mapped_column(Date)
    duration_days: Mapped[int | None] = mapped_column(Integer)
    growth_stage: Mapped[str | None] = mapped_column(String(60))          # farmer-set or computed
    health: Mapped[str | None] = mapped_column(String(20))                # GOOD | FAIR | POOR
    status: Mapped[CropStatus] = mapped_column(Enum(CropStatus), default=CropStatus.ACTIVE, index=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class CropRecord(Base):
    """One table for crop-wise irrigation / fertilizer / pesticide / expense / harvest / yield entries."""
    __tablename__ = "crop_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    crop_id: Mapped[int] = mapped_column(ForeignKey("crops.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)             # IRRIGATION|FERTILIZER|PESTICIDE|EXPENSE|HARVEST|YIELD|NOTE
    on_date: Mapped[date] = mapped_column(Date, index=True)
    product: Mapped[str | None] = mapped_column(String(160))
    quantity: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(20))
    amount_paise: Mapped[int | None] = mapped_column(Integer)             # cost (EXPENSE/FERTILIZER/PESTICIDE) or revenue (HARVEST)
    note: Mapped[str | None] = mapped_column(String(500))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class SoilReading(Base, TimestampMixin):
    """Soil data from manual entry, lab report or sensor summary."""
    __tablename__ = "soil_readings"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), index=True)
    field_id: Mapped[int | None] = mapped_column(ForeignKey("fields.id"), index=True)
    on_date: Mapped[date] = mapped_column(Date, index=True)
    source: Mapped[str] = mapped_column(String(20), default="MANUAL")     # MANUAL | LAB | SENSOR
    soil_type: Mapped[str | None] = mapped_column(String(60))
    ph: Mapped[float | None] = mapped_column(Float)
    nitrogen: Mapped[float | None] = mapped_column(Float)                 # kg/ha available N
    phosphorus: Mapped[float | None] = mapped_column(Float)               # kg/ha available P
    potassium: Mapped[float | None] = mapped_column(Float)                # kg/ha available K
    organic_carbon: Mapped[float | None] = mapped_column(Float)           # %
    ec: Mapped[float | None] = mapped_column(Float)                       # dS/m
    moisture: Mapped[float | None] = mapped_column(Float)                 # %
    booking_id: Mapped[int | None] = mapped_column(ForeignKey("soil_test_bookings.id"))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class SoilBookingStatus(str, enum.Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    SAMPLE_COLLECTED = "SAMPLE_COLLECTED"
    IN_TESTING = "IN_TESTING"
    REPORT_READY = "REPORT_READY"
    CANCELLED = "CANCELLED"


class SoilTestBooking(Base, TimestampMixin):
    __tablename__ = "soil_test_bookings"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    center_id: Mapped[int] = mapped_column(ForeignKey("soil_centers.id"), index=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"))
    field_id: Mapped[int | None] = mapped_column(ForeignKey("fields.id"))
    preferred_date: Mapped[date] = mapped_column(Date)
    collection: Mapped[str] = mapped_column(String(20), default="DROP_OFF")   # DROP_OFF | PICKUP
    status: Mapped[SoilBookingStatus] = mapped_column(Enum(SoilBookingStatus), default=SoilBookingStatus.REQUESTED, index=True)
    tracking_code: Mapped[str] = mapped_column(String(20), unique=True)
    fee_paise: Mapped[int] = mapped_column(Integer, default=0)
    interpretation: Mapped[str | None] = mapped_column(Text)              # lab / expert interpretation (human written)
    note: Mapped[str | None] = mapped_column(String(300))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
