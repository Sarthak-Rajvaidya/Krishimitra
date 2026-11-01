"""IoT: device-facing endpoints (token auth) and farmer / admin endpoints (session auth).
Devices push readings and PULL pump commands, so a pump is never reachable from the internet."""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field as F
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require
from app.core.audit import audit
from app.core.ratelimit import rate_limit
from app.db.base import as_utc, utcnow
from app.db.session import get_db
from app.models import (Device, Farm, Field, IrrigationConfig, IrrigationEvent, METRICS, PumpCommand, SensorHourly, SensorReading, User)
from app.services import iot as svc

router = APIRouter(prefix="/iot", tags=["iot"])
Own = Depends(require("iot.own"))
Admin = Depends(require("iot.admin"))


# ---------------- device side ----------------
def device_auth(x_device_uid: str = Header(...), x_device_token: str = Header(...), db: Session = Depends(get_db)) -> Device:
    d = db.scalar(select(Device).where(Device.uid == x_device_uid))
    if not d or not d.is_active or not svc.token_ok(d, x_device_token):
        raise HTTPException(401, "Invalid device credentials")
    rate_limit(f"dev:{d.id}", 120)
    return d


class Reading(BaseModel):
    metric: str = F(max_length=20)
    value: float
    ts: datetime | None = None


class IngestIn(BaseModel):
    readings: list[Reading] = F(min_length=1, max_length=60)
    battery_pct: float | None = None
    firmware: str | None = F(default=None, max_length=40)


@router.post("/ingest")
def ingest(body: IngestIn, d: Device = Depends(device_auth), db: Session = Depends(get_db)):
    if body.firmware:
        d.firmware = body.firmware
    n = svc.ingest(db, d, [r.model_dump() for r in body.readings], body.battery_pct)
    db.commit()
    return {"accepted": n}


@router.get("/device/commands")
def device_commands(d: Device = Depends(device_auth), db: Session = Depends(get_db)):
    """Device polls (every 15-60 s). Commands older than their expiry are never returned."""
    now = utcnow()
    cmds = db.scalars(select(PumpCommand).where(PumpCommand.device_id == d.id, PumpCommand.status.in_(("PENDING", "SENT")), PumpCommand.expires_at > now)
                      .order_by(PumpCommand.id).limit(5)).all()
    for c in cmds:
        c.status = "SENT"
    d.last_seen, d.connectivity = now, "ONLINE"
    db.commit()
    return [{"id": c.id, "action": c.action, "duration_min": c.duration_min} for c in cmds]


class AckIn(BaseModel):
    command_id: int
    ok: bool = True


@router.post("/device/ack")
def device_ack(body: AckIn, d: Device = Depends(device_auth), db: Session = Depends(get_db)):
    svc.ack_command(db, d, body.command_id, body.ok)
    db.commit()
    return {"ok": True}


# ---------------- farmer side ----------------
def _own(db: Session, user: User, did: int) -> Device:
    d = db.get(Device, did)
    if not d or d.owner_id != user.id:
        raise HTTPException(404, "Device not found")
    return d


def dev_out(db: Session, d: Device, with_latest: bool = True) -> dict:
    out = {"id": d.id, "uid": d.uid, "name": d.name, "kind": d.kind, "farm_id": d.farm_id, "field_id": d.field_id, "sensors": d.sensors or [],
           "connectivity": d.connectivity, "health": d.health, "battery_pct": d.battery_pct, "firmware": d.firmware,
           "last_seen": d.last_seen.isoformat() if d.last_seen else None, "config": {**svc.DEFAULT_ALERTS, **(d.config or {})}, "is_active": d.is_active}
    if with_latest:
        out["latest"] = svc.latest(db, d.id)
    return out


class RegisterIn(BaseModel):
    name: str = F(min_length=1, max_length=120)
    kind: str = F(default="NODE", pattern="^(NODE|PUMP_CONTROLLER|COMBO)$")
    farm_id: int
    field_id: int | None = None
    sensors: list[str] = F(default_factory=lambda: ["soil_moisture", "temperature", "humidity"], max_length=8)


@router.post("/devices", status_code=201)
def register(body: RegisterIn, user: User = Own, db: Session = Depends(get_db)):
    farm = db.get(Farm, body.farm_id)
    if not farm or farm.user_id != user.id or farm.deleted_at:
        raise HTTPException(404, "Farm not found")
    if body.field_id:
        f = db.get(Field, body.field_id)
        if not f or f.farm_id != farm.id:
            raise HTTPException(404, "Field not found")
    if db.scalar(select(func.count(Device.id)).where(Device.owner_id == user.id)) >= 50:
        raise HTTPException(409, "Device limit reached")
    if any(s not in METRICS for s in body.sensors):
        raise HTTPException(422, f"Sensors must be from {METRICS}")
    uid, token, th = svc.new_credentials()
    d = Device(uid=uid, token_hash=th, owner_id=user.id, farm_id=farm.id, field_id=body.field_id, name=body.name, kind=body.kind, sensors=body.sensors)
    db.add(d)
    db.flush()
    if body.kind in ("PUMP_CONTROLLER", "COMBO"):
        db.add(IrrigationConfig(device_id=d.id))
    audit(db, user.id, "iot.register", "device", d.id)
    db.commit()
    # the token is shown once; only its hash is stored
    return {**dev_out(db, d, False), "device_token": token, "note": "Save this token in the device now. It will not be shown again."}


@router.post("/devices/{did}/rotate-token")
def rotate(did: int, user: User = Own, db: Session = Depends(get_db)):
    d = _own(db, user, did)
    _, token, th = svc.new_credentials()
    d.token_hash = th
    db.commit()
    return {"device_token": token}


@router.get("/devices")
def my_devices(user: User = Own, db: Session = Depends(get_db)):
    return [dev_out(db, d) for d in db.scalars(select(Device).where(Device.owner_id == user.id, Device.is_active.is_(True)).order_by(Device.id))]


@router.delete("/devices/{did}")
def remove(did: int, user: User = Own, db: Session = Depends(get_db)):
    d = _own(db, user, did)
    d.is_active = False
    db.commit()
    return {"ok": True}


class AlertCfg(BaseModel):
    soil_moisture_low: float | None = F(default=None, ge=0, le=100)
    temperature_high: float | None = F(default=None, ge=0, le=70)
    water_level_low: float | None = F(default=None, ge=0, le=100)


@router.put("/devices/{did}/alerts")
def set_alerts(did: int, body: AlertCfg, user: User = Own, db: Session = Depends(get_db)):
    d = _own(db, user, did)
    d.config = {**(d.config or {}), **body.model_dump(exclude_none=True)}
    db.commit()
    return dev_out(db, d, False)


@router.get("/devices/{did}/history")
def history(did: int, metric: str, hours: int = Query(24, ge=1, le=24 * 90), user: User = Own, db: Session = Depends(get_db)):
    """Raw points for up to 48 h, hourly averages beyond that. Output is capped so charts stay light."""
    d = _own(db, user, did)
    if metric not in METRICS:
        raise HTTPException(422, "Unknown metric")
    since = utcnow() - timedelta(hours=hours)
    if hours <= 48:
        rows = db.execute(select(SensorReading.ts, SensorReading.value).where(SensorReading.device_id == d.id, SensorReading.metric == metric,
                                                                             SensorReading.ts >= since).order_by(SensorReading.ts.desc()).limit(600)).all()
        pts = [{"t": t.isoformat(), "v": v} for t, v in reversed(rows)]
    else:
        rows = db.execute(select(SensorHourly.hour, SensorHourly.avg, SensorHourly.min, SensorHourly.max)
                          .where(SensorHourly.device_id == d.id, SensorHourly.metric == metric, SensorHourly.hour >= since)
                          .order_by(SensorHourly.hour).limit(2200)).all()
        pts = [{"t": h.isoformat(), "v": round(a, 2), "min": lo, "max": hi} for h, a, lo, hi in rows]
    return {"metric": metric, "points": pts, "resolution": "raw" if hours <= 48 else "hourly"}


# ---------------- irrigation ----------------
class IrrigationIn(BaseModel):
    mode: str = F(pattern="^(MANUAL|AUTO|SCHEDULE)$")
    moisture_low: float = F(default=30, ge=5, le=80)
    moisture_high: float = F(default=60, ge=10, le=95)
    max_minutes: int = F(default=30, ge=1, le=240)
    min_gap_minutes: int = F(default=120, ge=10, le=1440)
    rain_lock: bool = True
    low_water_lock: bool = True
    water_level_min: float = F(default=15, ge=0, le=100)
    schedule: list[dict] | None = None


def _pump_dev(db: Session, user: User, did: int) -> Device:
    d = _own(db, user, did)
    if d.kind == "NODE":
        raise HTTPException(409, "This device has no pump controller")
    return d


@router.get("/devices/{did}/irrigation")
def get_irrigation(did: int, user: User = Own, db: Session = Depends(get_db)):
    d = _pump_dev(db, user, did)
    c = db.scalar(select(IrrigationConfig).where(IrrigationConfig.device_id == d.id))
    ev = db.scalars(select(IrrigationEvent).where(IrrigationEvent.device_id == d.id).order_by(IrrigationEvent.id.desc()).limit(20)).all()
    return {"config": {k: getattr(c, k) for k in ("mode", "moisture_low", "moisture_high", "max_minutes", "min_gap_minutes", "rain_lock",
                                                  "low_water_lock", "water_level_min", "schedule")} if c else None,
            "pump_running": svc.pump_running(db, d.id), "override_until": c.override_until.isoformat() if c and c.override_until else None,
            "history": [{"started_at": e.started_at.isoformat(), "minutes": e.minutes, "source": e.source} for e in ev]}


@router.put("/devices/{did}/irrigation")
def set_irrigation(did: int, body: IrrigationIn, user: User = Own, db: Session = Depends(get_db)):
    d = _pump_dev(db, user, did)
    if body.moisture_high <= body.moisture_low:
        raise HTTPException(422, "Stop level must be higher than start level")
    c = db.scalar(select(IrrigationConfig).where(IrrigationConfig.device_id == d.id)) or IrrigationConfig(device_id=d.id)
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    c.updated_by = user.id
    db.add(c)
    audit(db, user.id, "iot.irrigation_config", "device", d.id, {"mode": body.mode})
    db.commit()
    return {"ok": True}


class PumpIn(BaseModel):
    action: str = F(pattern="^(ON|OFF)$")
    minutes: int | None = F(default=None, ge=1, le=240)


@router.post("/devices/{did}/pump")
def pump(did: int, body: PumpIn, user: User = Own, db: Session = Depends(get_db)):
    """Manual control. A manual command pauses automation for an hour so the two never fight."""
    rate_limit(f"pump:{user.id}", 20)
    d = _pump_dev(db, user, did)
    if d.connectivity != "ONLINE":
        raise HTTPException(409, "Device is offline; the command would not reach the pump")
    if body.action == "ON":
        lt = svc.latest(db, d.id)
        cfg = db.scalar(select(IrrigationConfig).where(IrrigationConfig.device_id == d.id))
        if cfg and cfg.low_water_lock and "water_level" in lt and lt["water_level"]["value"] < cfg.water_level_min:
            raise HTTPException(409, "Water tank level is too low to run the pump")
    c = svc.send_command(db, d, body.action, "MANUAL", user.id, body.minutes, "Manual")
    cfg = db.scalar(select(IrrigationConfig).where(IrrigationConfig.device_id == d.id))
    if cfg:
        cfg.override_until = utcnow() + timedelta(hours=1)
    audit(db, user.id, "iot.pump", "device", d.id, {"action": body.action})
    db.commit()
    return {"command_id": c.id, "status": c.status, "minutes": c.duration_min}


# ---------------- admin ----------------
@router.get("/admin/devices")
def admin_devices(connectivity: str | None = None, page: int = 1, size: int = 50, user: User = Admin, db: Session = Depends(get_db)):
    size = max(1, min(size, 200))
    q = select(Device, User.full_name).join(User, User.id == Device.owner_id, isouter=True).order_by(Device.id.desc()).offset((max(page, 1) - 1) * size).limit(size)
    if connectivity:
        q = q.where(Device.connectivity == connectivity.upper())
    total = db.scalar(select(func.count(Device.id)))
    counts = dict(db.execute(select(Device.connectivity, func.count(Device.id)).where(Device.is_active.is_(True)).group_by(Device.connectivity)).all())
    return {"total": total, "by_connectivity": counts,
            "items": [{**dev_out(db, d, False), "owner": n, "maintenance_note": d.maintenance_note} for d, n in db.execute(q)]}


class MaintIn(BaseModel):
    health: str = F(pattern="^(OK|WARN|FAULT)$")
    note: str | None = F(default=None, max_length=300)


@router.put("/admin/devices/{did}/maintenance")
def maintenance(did: int, body: MaintIn, user: User = Admin, db: Session = Depends(get_db)):
    d = db.get(Device, did)
    if not d:
        raise HTTPException(404, "Device not found")
    d.health, d.maintenance_note = body.health, body.note
    audit(db, user.id, "iot.maintenance", "device", d.id, {"health": body.health})
    db.commit()
    return {"ok": True}


