"""Farmer-side farm management: farms, fields, crops, crop records, soil data, soil-test booking, weather, advisory."""
import secrets
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field as F
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require
from app.api.v1.common import page_args
from app.core.audit import audit
from app.db.base import utcnow
from app.db.session import get_db
from app.models import (Crop, CropKnowledge, CropRecord, CropStatus, Farm, Field, SoilBookingStatus, SoilCenter, SoilReading,
                        SoilTestBooking, User)
from app.services import advisory_rules as rules
from app.services.notify import notify
from app.services.weather import get_weather, weather_alerts

router = APIRouter(prefix="/farm", tags=["farm"])
Farmer = Depends(require("farm.manage"))


def _own_farm(db: Session, user: User, farm_id: int) -> Farm:
    f = db.get(Farm, farm_id)
    if not f or f.user_id != user.id or f.deleted_at:
        raise HTTPException(404, "Farm not found")
    return f


def _own_field(db: Session, farm: Farm, field_id: int | None) -> Field | None:
    if field_id is None:
        return None
    fl = db.get(Field, field_id)
    if not fl or fl.farm_id != farm.id or fl.deleted_at:
        raise HTTPException(404, "Field not found")
    return fl


def _own_crop(db: Session, user: User, crop_id: int) -> Crop:
    c = db.get(Crop, crop_id)
    if not c or c.user_id != user.id:
        raise HTTPException(404, "Crop not found")
    return c


# ---------------- farms ----------------
class FarmIn(BaseModel):
    name: str = F(min_length=1, max_length=160)
    village: str | None = None
    district: str | None = None
    state: str | None = None
    latitude: float | None = F(default=None, ge=-90, le=90)
    longitude: float | None = F(default=None, ge=-180, le=180)
    area_acres: float | None = F(default=None, gt=0, le=100000)
    soil_type: str | None = None
    irrigation_source: str | None = None
    boundary: list[list[float]] | None = None


def farm_out(f: Farm) -> dict:
    return {c: getattr(f, c) for c in ("id", "name", "village", "district", "state", "latitude", "longitude", "area_acres",
                                       "soil_type", "irrigation_source", "boundary")}


@router.get("/farms")
def list_farms(user: User = Farmer, db: Session = Depends(get_db)):
    return [farm_out(f) for f in db.scalars(select(Farm).where(Farm.user_id == user.id, Farm.deleted_at.is_(None)).order_by(Farm.id))]


@router.post("/farms", status_code=201)
def create_farm(body: FarmIn, user: User = Farmer, db: Session = Depends(get_db)):
    if db.scalar(select(func.count(Farm.id)).where(Farm.user_id == user.id, Farm.deleted_at.is_(None))) >= 20:
        raise HTTPException(409, "Farm limit reached")
    f = Farm(user_id=user.id, **body.model_dump())
    db.add(f)
    db.commit()
    return farm_out(f)


@router.put("/farms/{farm_id}")
def update_farm(farm_id: int, body: FarmIn, user: User = Farmer, db: Session = Depends(get_db)):
    f = _own_farm(db, user, farm_id)
    for k, v in body.model_dump().items():
        setattr(f, k, v)
    db.commit()
    return farm_out(f)


@router.delete("/farms/{farm_id}")
def delete_farm(farm_id: int, user: User = Farmer, db: Session = Depends(get_db)):
    f = _own_farm(db, user, farm_id)
    f.deleted_at = utcnow()
    db.commit()
    return {"ok": True}


# ---------------- fields ----------------
class FieldIn(BaseModel):
    name: str = F(min_length=1, max_length=120)
    area_acres: float | None = F(default=None, gt=0, le=100000)
    latitude: float | None = F(default=None, ge=-90, le=90)
    longitude: float | None = F(default=None, ge=-180, le=180)
    soil_type: str | None = None


@router.get("/farms/{farm_id}/fields")
def list_fields(farm_id: int, user: User = Farmer, db: Session = Depends(get_db)):
    _own_farm(db, user, farm_id)
    return [{"id": x.id, "name": x.name, "area_acres": x.area_acres, "soil_type": x.soil_type, "latitude": x.latitude, "longitude": x.longitude}
            for x in db.scalars(select(Field).where(Field.farm_id == farm_id, Field.deleted_at.is_(None)))]


@router.post("/farms/{farm_id}/fields", status_code=201)
def create_field(farm_id: int, body: FieldIn, user: User = Farmer, db: Session = Depends(get_db)):
    _own_farm(db, user, farm_id)
    x = Field(farm_id=farm_id, **body.model_dump())
    db.add(x)
    db.commit()
    return {"id": x.id}


@router.put("/fields/{field_id}")
def update_field(field_id: int, body: FieldIn, user: User = Farmer, db: Session = Depends(get_db)):
    x = db.get(Field, field_id)
    if not x or x.deleted_at:
        raise HTTPException(404, "Field not found")
    _own_farm(db, user, x.farm_id)
    for k, v in body.model_dump().items():
        setattr(x, k, v)
    db.commit()
    return {"ok": True}


@router.delete("/fields/{field_id}")
def delete_field(field_id: int, user: User = Farmer, db: Session = Depends(get_db)):
    x = db.get(Field, field_id)
    if not x:
        raise HTTPException(404, "Field not found")
    _own_farm(db, user, x.farm_id)
    x.deleted_at = utcnow()
    db.commit()
    return {"ok": True}


# ---------------- crops ----------------
class CropIn(BaseModel):
    farm_id: int
    field_id: int | None = None
    name: str = F(min_length=1, max_length=80)
    variety: str | None = None
    season: str | None = F(default=None, pattern="^(KHARIF|RABI|ZAID)$")
    area_acres: float | None = F(default=None, gt=0)
    sowing_date: date | None = None
    transplanting_date: date | None = None
    expected_harvest_date: date | None = None
    health: str | None = F(default=None, pattern="^(GOOD|FAIR|POOR)$")
    status: CropStatus = CropStatus.ACTIVE


def _knowledge(db: Session, name: str) -> CropKnowledge | None:
    return db.scalar(select(CropKnowledge).where(func.lower(CropKnowledge.crop) == name.strip().lower()))


def crop_out(c: Crop, k: CropKnowledge | None = None) -> dict:
    stage = c.growth_stage or (rules.growth_stage(k.stages, c.sowing_date, c.duration_days or k.duration_days) if k else None)
    days_left = (c.expected_harvest_date - date.today()).days if c.expected_harvest_date and c.status == CropStatus.ACTIVE else None
    return {"id": c.id, "farm_id": c.farm_id, "field_id": c.field_id, "name": c.name, "category": c.category, "variety": c.variety,
            "season": c.season, "area_acres": c.area_acres, "sowing_date": c.sowing_date, "transplanting_date": c.transplanting_date,
            "expected_harvest_date": c.expected_harvest_date, "actual_harvest_date": c.actual_harvest_date, "health": c.health,
            "status": c.status.value, "growth_stage": stage, "days_to_harvest": days_left}


@router.get("/crops")
def list_crops(farm_id: int | None = None, status: CropStatus | None = None, user: User = Farmer, db: Session = Depends(get_db)):
    q = select(Crop).where(Crop.user_id == user.id).order_by(Crop.id.desc()).limit(200)
    if farm_id:
        q = q.where(Crop.farm_id == farm_id)
    if status:
        q = q.where(Crop.status == status)
    kn = {k.crop.lower(): k for k in db.scalars(select(CropKnowledge))}
    return [crop_out(c, kn.get(c.name.lower())) for c in db.scalars(q)]


@router.post("/crops", status_code=201)
def create_crop(body: CropIn, user: User = Farmer, db: Session = Depends(get_db)):
    farm = _own_farm(db, user, body.farm_id)
    _own_field(db, farm, body.field_id)
    k = _knowledge(db, body.name)
    d = body.model_dump()
    c = Crop(user_id=user.id, category=k.category if k else None, duration_days=k.duration_days if k else None, **d)
    if c.sowing_date and not c.expected_harvest_date and k:
        c.expected_harvest_date = c.sowing_date + timedelta(days=k.duration_days)
    db.add(c)
    db.commit()
    return crop_out(c, k)


@router.put("/crops/{crop_id}")
def update_crop(crop_id: int, body: CropIn, user: User = Farmer, db: Session = Depends(get_db)):
    c = _own_crop(db, user, crop_id)
    farm = _own_farm(db, user, body.farm_id)
    _own_field(db, farm, body.field_id)
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    if body.status == CropStatus.HARVESTED and not c.actual_harvest_date:
        c.actual_harvest_date = date.today()
    db.commit()
    return crop_out(c, _knowledge(db, c.name))


# ---------------- crop records ----------------
KINDS = "^(IRRIGATION|FERTILIZER|PESTICIDE|EXPENSE|HARVEST|YIELD|NOTE)$"


class RecordIn(BaseModel):
    kind: str = F(pattern=KINDS)
    on_date: date
    product: str | None = F(default=None, max_length=160)
    quantity: float | None = F(default=None, ge=0)
    unit: str | None = F(default=None, max_length=20)
    amount_rupees: float | None = F(default=None, ge=0, le=100000000)
    note: str | None = F(default=None, max_length=500)


@router.get("/crops/{crop_id}/records")
def list_records(crop_id: int, user: User = Farmer, db: Session = Depends(get_db)):
    _own_crop(db, user, crop_id)
    rows = db.scalars(select(CropRecord).where(CropRecord.crop_id == crop_id).order_by(CropRecord.on_date.desc(), CropRecord.id.desc()).limit(500))
    return [{"id": r.id, "kind": r.kind, "on_date": r.on_date, "product": r.product, "quantity": r.quantity, "unit": r.unit,
             "amount_paise": r.amount_paise, "note": r.note} for r in rows]


@router.post("/crops/{crop_id}/records", status_code=201)
def add_record(crop_id: int, body: RecordIn, user: User = Farmer, db: Session = Depends(get_db)):
    _own_crop(db, user, crop_id)
    r = CropRecord(crop_id=crop_id, user_id=user.id, kind=body.kind, on_date=body.on_date, product=body.product, quantity=body.quantity,
                   unit=body.unit, amount_paise=round(body.amount_rupees * 100) if body.amount_rupees is not None else None, note=body.note)
    db.add(r)
    db.commit()
    return {"id": r.id}


@router.delete("/records/{rid}")
def delete_record(rid: int, user: User = Farmer, db: Session = Depends(get_db)):
    r = db.get(CropRecord, rid)
    if not r or r.user_id != user.id:
        raise HTTPException(404, "Record not found")
    db.delete(r)
    db.commit()
    return {"ok": True}


@router.get("/crops/{crop_id}/summary")
def crop_summary(crop_id: int, user: User = Farmer, db: Session = Depends(get_db)):
    """Cost, revenue and profit for one crop, computed from its records."""
    _own_crop(db, user, crop_id)
    rows = db.execute(select(CropRecord.kind, func.coalesce(func.sum(CropRecord.amount_paise), 0), func.coalesce(func.sum(CropRecord.quantity), 0))
                      .where(CropRecord.crop_id == crop_id).group_by(CropRecord.kind)).all()
    by = {k: (int(a), float(q)) for k, a, q in rows}
    cost = sum(by.get(k, (0, 0))[0] for k in ("EXPENSE", "FERTILIZER", "PESTICIDE", "IRRIGATION"))
    revenue = by.get("HARVEST", (0, 0))[0]
    return {"cost_paise": cost, "revenue_paise": revenue, "profit_paise": revenue - cost, "yield_qty": by.get("YIELD", (0, 0.0))[1],
            "by_kind": {k: {"amount_paise": a, "quantity": q} for k, (a, q) in by.items()}}


# ---------------- soil data ----------------
class SoilIn(BaseModel):
    farm_id: int
    field_id: int | None = None
    on_date: date
    soil_type: str | None = None
    ph: float | None = F(default=None, ge=0, le=14)
    nitrogen: float | None = F(default=None, ge=0, le=5000)
    phosphorus: float | None = F(default=None, ge=0, le=500)
    potassium: float | None = F(default=None, ge=0, le=5000)
    organic_carbon: float | None = F(default=None, ge=0, le=20)
    ec: float | None = F(default=None, ge=0, le=50)
    moisture: float | None = F(default=None, ge=0, le=100)


def soil_out(s: SoilReading) -> dict:
    d = {c: getattr(s, c) for c in ("id", "farm_id", "field_id", "on_date", "source", "soil_type", "ph", "nitrogen", "phosphorus",
                                    "potassium", "organic_carbon", "ec", "moisture")}
    d["findings"] = rules.soil_findings(s)
    return d


@router.get("/soil")
def list_soil(farm_id: int | None = None, user: User = Farmer, db: Session = Depends(get_db)):
    q = select(SoilReading).where(SoilReading.user_id == user.id).order_by(SoilReading.on_date.desc(), SoilReading.id.desc()).limit(100)
    if farm_id:
        q = q.where(SoilReading.farm_id == farm_id)
    return [soil_out(s) for s in db.scalars(q)]


@router.post("/soil", status_code=201)
def add_soil(body: SoilIn, user: User = Farmer, db: Session = Depends(get_db)):
    farm = _own_farm(db, user, body.farm_id)
    _own_field(db, farm, body.field_id)
    s = SoilReading(user_id=user.id, source="MANUAL", **body.model_dump())
    db.add(s)
    db.commit()
    return soil_out(s)


# ---------------- soil test booking ----------------
class BookingIn(BaseModel):
    center_id: int
    farm_id: int
    field_id: int | None = None
    preferred_date: date
    collection: str = F(default="DROP_OFF", pattern="^(DROP_OFF|PICKUP)$")
    note: str | None = F(default=None, max_length=300)


def booking_out(b: SoilTestBooking, center: SoilCenter | None = None) -> dict:
    return {"id": b.id, "tracking_code": b.tracking_code, "status": b.status.value, "preferred_date": b.preferred_date,
            "collection": b.collection, "fee_paise": b.fee_paise, "center_id": b.center_id,
            "center_name": center.name if center else None, "interpretation": b.interpretation, "created_at": b.created_at.isoformat()}


@router.get("/soil-centers")
def soil_centers(district: str | None = None, user: User = Depends(require("soil.book")), db: Session = Depends(get_db)):
    q = select(SoilCenter).where(SoilCenter.is_active.is_(True)).limit(100)
    if district:
        q = q.where(func.lower(SoilCenter.district) == district.lower())
    return [{"id": c.id, "name": c.name, "address": c.address, "district": c.district, "phone": c.phone, "fee_paise": c.test_fee_paise,
             "latitude": c.latitude, "longitude": c.longitude} for c in db.scalars(q)]


@router.post("/soil-tests", status_code=201)
def book_soil_test(body: BookingIn, user: User = Depends(require("soil.book")), db: Session = Depends(get_db)):
    farm = _own_farm(db, user, body.farm_id)
    _own_field(db, farm, body.field_id)
    center = db.get(SoilCenter, body.center_id)
    if not center or not center.is_active:
        raise HTTPException(404, "Soil testing centre not found")
    if body.preferred_date < date.today():
        raise HTTPException(422, "Choose today or a later date")
    b = SoilTestBooking(user_id=user.id, center_id=center.id, farm_id=farm.id, field_id=body.field_id, preferred_date=body.preferred_date,
                        collection=body.collection, fee_paise=center.test_fee_paise, note=body.note,
                        tracking_code="ST" + secrets.token_hex(4).upper())
    db.add(b)
    db.flush()
    if center.user_id:
        notify(db, center.user_id, "SOIL_BOOKING", "New soil test request", f"{user.full_name} - {b.tracking_code}")
    db.commit()
    return booking_out(b, center)


@router.get("/soil-tests")
def my_soil_tests(user: User = Depends(require("soil.book")), db: Session = Depends(get_db), page: int = 1, size: int = 20):
    off, size = page_args(page, size)
    rows = db.execute(select(SoilTestBooking, SoilCenter).join(SoilCenter, SoilCenter.id == SoilTestBooking.center_id)
                      .where(SoilTestBooking.user_id == user.id).order_by(SoilTestBooking.id.desc()).offset(off).limit(size)).all()
    return [booking_out(b, c) for b, c in rows]


@router.post("/soil-tests/{bid}/cancel")
def cancel_soil_test(bid: int, user: User = Depends(require("soil.book")), db: Session = Depends(get_db)):
    b = db.get(SoilTestBooking, bid)
    if not b or b.user_id != user.id:
        raise HTTPException(404, "Booking not found")
    if b.status not in (SoilBookingStatus.REQUESTED, SoilBookingStatus.CONFIRMED):
        raise HTTPException(409, "Sample already collected; cannot cancel")
    b.status = SoilBookingStatus.CANCELLED
    db.commit()
    return {"ok": True}


# ---------------- weather & advisory ----------------
def _farm_coords(db: Session, user: User, farm_id: int) -> tuple[Farm, float, float]:
    f = _own_farm(db, user, farm_id)
    if f.latitude is None or f.longitude is None:
        raise HTTPException(422, "Add the farm's location (latitude/longitude) to get weather")
    return f, f.latitude, f.longitude


@router.get("/farms/{farm_id}/weather")
def farm_weather(farm_id: int, user: User = Farmer, db: Session = Depends(get_db)):
    _, lat, lon = _farm_coords(db, user, farm_id)
    w = get_weather(lat, lon)
    if not w:
        raise HTTPException(503, "Weather service is not reachable right now. Try again shortly.")
    return {**w, "alerts": weather_alerts(w)}


@router.get("/farms/{farm_id}/advisory")
def farm_advisory(farm_id: int, user: User = Depends(require("farm.manage", "ai.use")), db: Session = Depends(get_db)):
    """Rule-based advice per active crop: irrigation, stage, soil. Every item shows the rule inputs."""
    farm = _own_farm(db, user, farm_id)
    soil = db.scalar(select(SoilReading).where(SoilReading.farm_id == farm.id).order_by(SoilReading.on_date.desc(), SoilReading.id.desc()).limit(1))
    w = get_weather(farm.latitude, farm.longitude) if farm.latitude is not None and farm.longitude is not None else None
    rain3 = sum((d["rain_mm"] or 0) for d in (w["daily"][:3] if w else []))
    tmax = w["daily"][0]["max_c"] if w and w["daily"] else None
    crops = db.scalars(select(Crop).where(Crop.farm_id == farm.id, Crop.status == CropStatus.ACTIVE)).all()
    kn = {k.crop.lower(): k for k in db.scalars(select(CropKnowledge))}
    out = []
    for c in crops:
        k = kn.get(c.name.lower())
        item = {"crop_id": c.id, "crop": c.name, "stage": crop_out(c, k)["growth_stage"],
                "irrigation": rules.irrigation_advice(k, soil.moisture if soil else None, rain3, tmax)}
        if k and tmax is not None and k.temp_max_c and tmax > k.temp_max_c:
            item["heat_warning"] = f"Forecast {tmax}°C is above {k.temp_max_c}°C heat-stress level for {c.name}."
        out.append(item)
    return {"crops": out, "soil": soil_out(soil) if soil else None, "alerts": weather_alerts(w), "disclaimer": rules.DISCLAIMER}


@router.get("/crop-suggestions")
def crop_suggestions(farm_id: int, season: str | None = Query(default=None, pattern="^(KHARIF|RABI|ZAID)$"),
                     user: User = Depends(require("farm.manage", "ai.use")), db: Session = Depends(get_db)):
    farm = _own_farm(db, user, farm_id)
    soil = db.scalar(select(SoilReading).where(SoilReading.farm_id == farm.id).order_by(SoilReading.on_date.desc()).limit(1))
    ph = soil.ph if soil else None
    st = (soil.soil_type if soil and soil.soil_type else farm.soil_type)
    ranked = sorted((rules.crop_suitability(k, ph, st, season) for k in db.scalars(select(CropKnowledge))), key=lambda x: -x["score"])
    audit(db, user.id, "advisory.crop_suggest", "farm", farm.id)
    db.commit()
    return {"suggestions": ranked[:8], "based_on": {"ph": ph, "soil_type": st, "season": season}, "disclaimer": rules.DISCLAIMER}
