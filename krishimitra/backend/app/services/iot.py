"""IoT ingest, alerting, irrigation automation and rollups.

Safety rules for the pump (all enforced server-side, in this order):
  1. farmer manual override pauses automation        4. never start when tank level is below the minimum
  2. never exceed max_minutes per run                5. skip when it is raining / meaningful rain is forecast
  3. keep min_gap_minutes between automatic runs     6. stale data (>30 min) never starts the pump
"""
import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.base import as_utc, utcnow
from app.models import (Device, DeviceLatest, Farm, IrrigationConfig, IrrigationEvent, METRICS, PumpCommand, SensorHourly, SensorReading)
from app.services.notify import notify
from app.services.weather import get_weather

RANGES = {"soil_moisture": (0, 100), "temperature": (-20, 70), "humidity": (0, 100), "rain": (0, 500), "water_level": (0, 100), "pump": (0, 1)}
DEFAULT_ALERTS = {"soil_moisture_low": 25, "temperature_high": 42, "water_level_low": 15}
STALE_MIN = 30


def new_credentials() -> tuple[str, str, str]:
    uid = "KM-" + secrets.token_hex(4).upper()
    token = secrets.token_urlsafe(24)
    return uid, token, hashlib.sha256(token.encode()).hexdigest()


def token_ok(device: Device, token: str) -> bool:
    return secrets.compare_digest(device.token_hash, hashlib.sha256(token.encode()).hexdigest())


def ingest(db: Session, device: Device, readings: list[dict], battery: float | None = None) -> int:
    """Store readings, refresh the 'latest' snapshot, then run alerts and automation. Returns the number accepted."""
    now = utcnow()
    accepted, newest = 0, {}
    for r in readings:
        m, v = r["metric"], r["value"]
        lo, hi = RANGES.get(m, (None, None))
        if m not in METRICS or lo is None or not (lo <= v <= hi):
            continue
        ts = as_utc(r["ts"]) if r.get("ts") else now
        if ts > now + timedelta(minutes=5) or ts < now - timedelta(days=2):
            ts = now                                     # reject nonsense device clocks
        db.add(SensorReading(device_id=device.id, metric=m, ts=ts, value=v))
        if m not in newest or ts >= newest[m][0]:
            newest[m] = (ts, v)
        accepted += 1
    for m, (ts, v) in newest.items():
        row = db.scalar(select(DeviceLatest).where(DeviceLatest.device_id == device.id, DeviceLatest.metric == m))
        if row:
            if ts >= as_utc(row.ts):
                row.value, row.ts = v, ts
        else:
            db.add(DeviceLatest(device_id=device.id, metric=m, value=v, ts=ts))
    device.last_seen, device.connectivity = now, "ONLINE"
    if battery is not None:
        device.battery_pct = max(0.0, min(100.0, battery))
    db.flush()
    if accepted:
        check_alerts(db, device, {m: v for m, (_, v) in newest.items()})
        run_automation(db, device)
    return accepted


def latest(db: Session, device_id: int) -> dict[str, dict]:
    return {r.metric: {"value": r.value, "ts": r.ts.isoformat()} for r in db.scalars(select(DeviceLatest).where(DeviceLatest.device_id == device_id))}


def check_alerts(db: Session, d: Device, values: dict[str, float]) -> None:
    cfg = {**DEFAULT_ALERTS, **(d.config or {})}
    checks = (("soil_moisture", lambda v: v < cfg["soil_moisture_low"], "Soil is dry", "Soil moisture {v:.0f}% is below {t}%.", cfg["soil_moisture_low"]),
              ("temperature", lambda v: v > cfg["temperature_high"], "High temperature", "Temperature {v:.0f}°C is above {t}°C.", cfg["temperature_high"]),
              ("water_level", lambda v: v < cfg["water_level_low"], "Water tank low", "Water level {v:.0f}% is below {t}%.", cfg["water_level_low"]))
    if not d.owner_id:
        return
    for metric, bad, title, text, thr in checks:
        v = values.get(metric)
        if v is not None and bad(v):
            notify(db, d.owner_id, "IOT", f"{title} - {d.name or d.uid}", text.format(v=v, t=thr), data={"device_id": d.id},
                   dedupe_key=f"iot{d.id}{metric}", dedupe_hours=6, sms=metric == "water_level")
    if d.battery_pct is not None and d.battery_pct < 15:
        notify(db, d.owner_id, "IOT", f"Low battery - {d.name or d.uid}", f"Battery is {d.battery_pct:.0f}%.", dedupe_key=f"iot{d.id}bat", dedupe_hours=24)


def mark_offline(db: Session) -> int:
    """Worker job: devices silent for iot_offline_minutes become OFFLINE and the owner is told once."""
    cutoff = utcnow() - timedelta(minutes=get_settings().iot_offline_minutes)
    n = 0
    for d in db.scalars(select(Device).where(Device.is_active.is_(True), Device.connectivity == "ONLINE", Device.last_seen < cutoff)):
        d.connectivity = "OFFLINE"
        n += 1
        if d.owner_id:
            notify(db, d.owner_id, "IOT", f"Device offline - {d.name or d.uid}", "No data received. Check power and network.", dedupe_key=f"iot{d.id}off", dedupe_hours=12, sms=True)
    db.commit()
    return n


def _active_command(db: Session, device_id: int) -> PumpCommand | None:
    return db.scalar(select(PumpCommand).where(PumpCommand.device_id == device_id, PumpCommand.status.in_(("PENDING", "SENT"))).order_by(PumpCommand.id.desc()).limit(1))


def pump_running(db: Session, device_id: int) -> bool:
    return bool(db.scalar(select(IrrigationEvent.id).where(IrrigationEvent.device_id == device_id, IrrigationEvent.ended_at.is_(None)).limit(1)))


def send_command(db: Session, d: Device, action: str, source: str, user_id: int | None, minutes: int | None = None, reason: str | None = None) -> PumpCommand:
    cfg = db.scalar(select(IrrigationConfig).where(IrrigationConfig.device_id == d.id))
    cap = cfg.max_minutes if cfg else 30
    if action == "ON":
        minutes = min(minutes or cap, cap)             # the cap applies to manual runs too
    now = utcnow()
    c = PumpCommand(device_id=d.id, action=action, duration_min=minutes if action == "ON" else None, source=source, reason=reason,
                    requested_by=user_id, created_at=now, expires_at=now + timedelta(minutes=10))
    db.add(c)
    db.flush()
    return c


def run_automation(db: Session, d: Device) -> PumpCommand | None:
    cfg = db.scalar(select(IrrigationConfig).where(IrrigationConfig.device_id == d.id))
    if not cfg or cfg.mode != "AUTO" or d.kind == "NODE":
        return None
    now = utcnow()
    if cfg.override_until and as_utc(cfg.override_until) > now:
        return None
    lt = latest(db, d.id)
    moist = lt.get("soil_moisture")
    if not moist or (now - datetime.fromisoformat(moist["ts"])).total_seconds() > STALE_MIN * 60:
        return None
    if _active_command(db, d.id):
        return None
    running = pump_running(db, d.id)
    if running and moist["value"] >= cfg.moisture_high:
        return send_command(db, d, "OFF", "AUTO", None, reason=f"Moisture reached {moist['value']:.0f}%")
    if running or moist["value"] >= cfg.moisture_low:
        return None
    # --- start conditions: every lock must pass ---
    if cfg.low_water_lock and "water_level" in lt and lt["water_level"]["value"] < cfg.water_level_min:
        _blocked(db, d, "Tank level too low")
        return None
    if cfg.rain_lock:
        if lt.get("rain", {}).get("value", 0) > 0:
            return None
        f = db.get(Farm, d.farm_id) if d.farm_id else None
        w = get_weather(f.latitude, f.longitude) if f and f.latitude is not None and f.longitude is not None else None
        if w and w["daily"] and (w["daily"][0]["rain_mm"] or 0) >= 5:
            return None
    last = db.scalar(select(func.max(IrrigationEvent.started_at)).where(IrrigationEvent.device_id == d.id, IrrigationEvent.source == "AUTO"))
    if last and (now - as_utc(last)).total_seconds() < cfg.min_gap_minutes * 60:
        return None
    return send_command(db, d, "ON", "AUTO", None, cfg.max_minutes, f"Moisture {moist['value']:.0f}% below {cfg.moisture_low:.0f}%")


def _blocked(db: Session, d: Device, why: str) -> None:
    if d.owner_id:
        notify(db, d.owner_id, "IRRIGATION", f"Irrigation held - {d.name or d.uid}", why, dedupe_key=f"irrblock{d.id}", dedupe_hours=6)


def ack_command(db: Session, d: Device, cmd_id: int, ok: bool = True) -> None:
    c = db.get(PumpCommand, cmd_id)
    if not c or c.device_id != d.id or c.status in ("ACKED", "EXPIRED"):
        return
    now = utcnow()
    c.status, c.acked_at = ("ACKED" if ok else "EXPIRED"), now
    if not ok:
        return
    if c.action == "ON" and not pump_running(db, d.id):
        db.add(IrrigationEvent(device_id=d.id, field_id=d.field_id, started_at=now, source=c.source))
        if d.owner_id and c.source == "AUTO":
            notify(db, d.owner_id, "IRRIGATION", f"Pump started - {d.name or d.uid}", c.reason or "Automatic irrigation", dedupe_key=f"pumpon{c.id}")
    elif c.action == "OFF":
        close_events(db, d.id, now)


def close_events(db: Session, device_id: int, now: datetime) -> None:
    for e in db.scalars(select(IrrigationEvent).where(IrrigationEvent.device_id == device_id, IrrigationEvent.ended_at.is_(None))):
        e.ended_at, e.minutes = now, round((now - as_utc(e.started_at)).total_seconds() / 60, 1)


def expire_commands(db: Session) -> None:
    """Worker job: stale commands expire; an ON run that was never switched off is closed at its max duration."""
    now = utcnow()
    for c in db.scalars(select(PumpCommand).where(PumpCommand.status.in_(("PENDING", "SENT")), PumpCommand.expires_at < now)):
        c.status = "EXPIRED"
    for e in db.scalars(select(IrrigationEvent).where(IrrigationEvent.ended_at.is_(None))):
        cfg = db.scalar(select(IrrigationConfig).where(IrrigationConfig.device_id == e.device_id))
        if now - as_utc(e.started_at) > timedelta(minutes=(cfg.max_minutes if cfg else 30) + 5):
            e.ended_at, e.minutes = now, round((now - as_utc(e.started_at)).total_seconds() / 60, 1)
            dev = db.get(Device, e.device_id)
            if dev:
                db.add(PumpCommand(device_id=dev.id, action="OFF", source="SAFETY", reason="Maximum run time reached", created_at=now, expires_at=now + timedelta(minutes=10)))
    db.commit()


def rollup_hourly(db: Session, hours_back: int = 3) -> int:
    """Aggregate raw readings of completed hours into SensorHourly (idempotent)."""
    now = utcnow().replace(minute=0, second=0, microsecond=0)
    n = 0
    for h in range(1, hours_back + 1):
        start, end = now - timedelta(hours=h), now - timedelta(hours=h - 1)
        rows = db.execute(select(SensorReading.device_id, SensorReading.metric, func.avg(SensorReading.value), func.min(SensorReading.value),
                                 func.max(SensorReading.value), func.count(SensorReading.id))
                          .where(SensorReading.ts >= start, SensorReading.ts < end).group_by(SensorReading.device_id, SensorReading.metric)).all()
        for dev, m, a, lo, hi, c in rows:
            row = db.scalar(select(SensorHourly).where(SensorHourly.device_id == dev, SensorHourly.metric == m, SensorHourly.hour == start))
            if row:
                row.avg, row.min, row.max, row.n = a, lo, hi, c
            else:
                db.add(SensorHourly(device_id=dev, metric=m, hour=start, avg=a, min=lo, max=hi, n=c))
            n += 1
    db.commit()
    return n


def purge_raw(db: Session) -> int:
    cutoff = utcnow() - timedelta(days=get_settings().iot_raw_retention_days)
    res = db.execute(delete(SensorReading).where(SensorReading.ts < cutoff))
    db.commit()
    return res.rowcount or 0


def run_schedules(db: Session) -> int:
    """Worker job (every minute): start pumps whose SCHEDULE entry is due. Times are Indian Standard Time."""
    from zoneinfo import ZoneInfo
    now_ist = utcnow().astimezone(ZoneInfo("Asia/Kolkata"))
    day = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][now_ist.weekday()]
    n = 0
    for cfg in db.scalars(select(IrrigationConfig).where(IrrigationConfig.mode == "SCHEDULE")):
        d = db.get(Device, cfg.device_id)
        if not d or not d.is_active or d.connectivity != "ONLINE" or (cfg.override_until and as_utc(cfg.override_until) > utcnow()):
            continue
        for slot in cfg.schedule or []:
            try:
                hh, mm = (int(x) for x in str(slot["time"]).split(":"))
            except (KeyError, ValueError):
                continue
            if day in [x.lower() for x in slot.get("days", [])] and now_ist.hour == hh and now_ist.minute == mm and not _active_command(db, d.id) and not pump_running(db, d.id):
                lt = latest(db, d.id)
                if cfg.low_water_lock and "water_level" in lt and lt["water_level"]["value"] < cfg.water_level_min:
                    _blocked(db, d, "Tank level too low for the scheduled run")
                    continue
                send_command(db, d, "ON", "SCHEDULE", None, int(slot.get("minutes", 20)), f"Scheduled {slot['time']}")
                n += 1
    db.commit()
    return n
