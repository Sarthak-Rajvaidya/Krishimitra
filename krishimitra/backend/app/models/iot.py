"""IoT devices, readings, irrigation control. Designed for high write volume: narrow rows, composite indexes,
a 'latest' table for dashboards and hourly rollups for history/retention."""
import enum
from datetime import datetime

from sqlalchemy import (BigInteger, Boolean, DateTime, Enum, Float, ForeignKey, Index, Integer, JSON, String,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

METRICS = ("soil_moisture", "temperature", "humidity", "rain", "water_level", "pump")


class Device(Base, TimestampMixin):
    __tablename__ = "devices"
    id: Mapped[int] = mapped_column(primary_key=True)
    uid: Mapped[str] = mapped_column(String(40), unique=True, index=True)            # printed on the hardware
    token_hash: Mapped[str] = mapped_column(String(64))                              # sha256 of the device secret
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    farm_id: Mapped[int | None] = mapped_column(ForeignKey("farms.id"), index=True)
    field_id: Mapped[int | None] = mapped_column(ForeignKey("fields.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    kind: Mapped[str] = mapped_column(String(30), default="NODE")                    # NODE | PUMP_CONTROLLER | COMBO
    sensors: Mapped[list | None] = mapped_column(JSON)                               # enabled metrics, e.g. ["soil_moisture","temperature"]
    config: Mapped[dict | None] = mapped_column(JSON)                                # alert thresholds {"soil_moisture_low":25,...}
    firmware: Mapped[str | None] = mapped_column(String(40))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    connectivity: Mapped[str] = mapped_column(String(12), default="UNKNOWN")         # ONLINE | OFFLINE | UNKNOWN
    health: Mapped[str] = mapped_column(String(12), default="OK")                    # OK | WARN | FAULT
    battery_pct: Mapped[float | None] = mapped_column(Float)
    maintenance_note: Mapped[str | None] = mapped_column(String(300))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class DeviceLatest(Base):
    __tablename__ = "device_latest"
    __table_args__ = (UniqueConstraint("device_id", "metric"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    metric: Mapped[str] = mapped_column(String(20))
    value: Mapped[float] = mapped_column(Float)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SensorReading(Base):
    __tablename__ = "sensor_readings"
    __table_args__ = (Index("ix_reading_dev_metric_ts", "device_id", "metric", "ts"),)
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    metric: Mapped[str] = mapped_column(String(20))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    value: Mapped[float] = mapped_column(Float)


class SensorHourly(Base):
    __tablename__ = "sensor_hourly"
    __table_args__ = (UniqueConstraint("device_id", "metric", "hour"),)
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    metric: Mapped[str] = mapped_column(String(20))
    hour: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    avg: Mapped[float] = mapped_column(Float)
    min: Mapped[float] = mapped_column(Float)
    max: Mapped[float] = mapped_column(Float)
    n: Mapped[int] = mapped_column(Integer)


class IrrigationConfig(Base, TimestampMixin):
    __tablename__ = "irrigation_configs"
    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), unique=True)
    mode: Mapped[str] = mapped_column(String(10), default="MANUAL")                  # MANUAL | AUTO | SCHEDULE
    moisture_low: Mapped[float] = mapped_column(Float, default=30)                   # start pump below this %
    moisture_high: Mapped[float] = mapped_column(Float, default=60)                  # stop above this %
    max_minutes: Mapped[int] = mapped_column(Integer, default=30)                    # hard cap per run
    min_gap_minutes: Mapped[int] = mapped_column(Integer, default=120)               # rest between auto runs
    rain_lock: Mapped[bool] = mapped_column(Boolean, default=True)                   # skip auto-irrigation when raining / rain forecast
    low_water_lock: Mapped[bool] = mapped_column(Boolean, default=True)              # never run pump if tank level is low
    water_level_min: Mapped[float] = mapped_column(Float, default=15)
    schedule: Mapped[list | None] = mapped_column(JSON)                              # [{"days":["mon","thu"],"time":"06:00","minutes":20}]
    override_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # manual override pauses automation until then
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class PumpCommand(Base):
    __tablename__ = "pump_commands"
    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(4))                       # ON | OFF
    duration_min: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(10))                      # MANUAL | AUTO | SCHEDULE | SAFETY
    reason: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(8), default="PENDING", index=True)   # PENDING | SENT | ACKED | EXPIRED
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IrrigationEvent(Base):
    """History of pump runs (one row per ON..OFF cycle)."""
    __tablename__ = "irrigation_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    field_id: Mapped[int | None] = mapped_column(ForeignKey("fields.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(10))
    minutes: Mapped[float | None] = mapped_column(Float)
