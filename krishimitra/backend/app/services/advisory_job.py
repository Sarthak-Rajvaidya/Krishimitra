"""Daily job: turns weather, soil and crop data into Advisory rows (deduplicated per day) and notifies the farmer."""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import Advisory, Crop, CropKnowledge, CropStatus, Farm, SoilReading
from app.services import advisory_rules as rules
from app.services.notify import notify
from app.services.weather import get_weather, weather_alerts


def _add(db: Session, farm: Farm, key: str, category: str, severity: str, title: str, body: str, evidence: dict, crop_id: int | None = None) -> None:
    dk = f"{key}:{date.today().isoformat()}"
    if db.scalar(select(Advisory.id).where(Advisory.user_id == farm.user_id, Advisory.dedupe_key == dk)):
        return
    db.add(Advisory(user_id=farm.user_id, farm_id=farm.id, crop_id=crop_id, category=category, severity=severity, title=title, body=body,
                    evidence=evidence, source="RULE", dedupe_key=dk, created_at=utcnow()))
    if severity != "INFO":
        notify(db, farm.user_id, "ADVISORY", title, body[:200], dedupe_key=dk, dedupe_hours=24)


def run(db: Session, batch: int = 500) -> int:
    n = 0
    kn = {k.crop.lower(): k for k in db.scalars(select(CropKnowledge))}
    for farm in db.scalars(select(Farm).where(Farm.deleted_at.is_(None), Farm.latitude.is_not(None)).limit(batch)):
        w = get_weather(farm.latitude, farm.longitude)
        for a in weather_alerts(w):
            _add(db, farm, f"w{farm.id}{a['kind']}", "WEATHER", "ACTION" if a["kind"] in ("HEAVY_RAIN", "HEAT") else "WATCH", a["text"].split(".")[0], a["text"], {"date": a["date"]})
            n += 1
        soil = db.scalar(select(SoilReading).where(SoilReading.farm_id == farm.id).order_by(SoilReading.on_date.desc()).limit(1))
        rain3 = sum((d["rain_mm"] or 0) for d in (w["daily"][:3] if w else []))
        tmax = w["daily"][0]["max_c"] if w and w["daily"] else None
        for c in db.scalars(select(Crop).where(Crop.farm_id == farm.id, Crop.status == CropStatus.ACTIVE)):
            k = kn.get(c.name.lower())
            adv = rules.irrigation_advice(k, soil.moisture if soil else None, rain3, tmax)
            if adv["action"] == "IRRIGATE":
                _add(db, farm, f"irr{c.id}", "IRRIGATION", "ACTION", f"{c.name}: irrigation needed", adv["reason"], adv["inputs"], c.id)
                n += 1
            if c.expected_harvest_date and 0 <= (c.expected_harvest_date - date.today()).days <= 7:
                _add(db, farm, f"hv{c.id}", "HARVEST", "WATCH", f"{c.name}: harvest due soon", f"Expected harvest on {c.expected_harvest_date}.", {"expected": str(c.expected_harvest_date)}, c.id)
                n += 1
    db.commit()
    return n
