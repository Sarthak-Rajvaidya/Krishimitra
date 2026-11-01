"""Soil testing centre console: incoming bookings, status updates, results entry."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field as F
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require
from app.db.session import get_db
from app.models import SoilBookingStatus, SoilCenter, SoilReading, SoilTestBooking, User
from app.services.notify import notify

router = APIRouter(prefix="/soil-center", tags=["soil-center"])
ORDER = [SoilBookingStatus.REQUESTED, SoilBookingStatus.CONFIRMED, SoilBookingStatus.SAMPLE_COLLECTED,
         SoilBookingStatus.IN_TESTING, SoilBookingStatus.REPORT_READY]


def _center(db: Session, user: User) -> SoilCenter:
    c = db.scalar(select(SoilCenter).where(SoilCenter.user_id == user.id))
    if not c:
        raise HTTPException(404, "No centre linked to this account")
    return c


@router.get("/bookings")
def bookings(status: SoilBookingStatus | None = None, user: User = Depends(require("soilcenter.work")), db: Session = Depends(get_db)):
    c = _center(db, user)
    q = select(SoilTestBooking, User).join(User, User.id == SoilTestBooking.user_id).where(SoilTestBooking.center_id == c.id) \
        .order_by(SoilTestBooking.id.desc()).limit(200)
    if status:
        q = q.where(SoilTestBooking.status == status)
    return [{"id": b.id, "tracking_code": b.tracking_code, "status": b.status.value, "farmer": u.full_name, "farmer_phone": u.phone,
             "preferred_date": b.preferred_date, "collection": b.collection, "farm_id": b.farm_id, "note": b.note} for b, u in db.execute(q)]


class StatusIn(BaseModel):
    status: SoilBookingStatus


@router.post("/bookings/{bid}/status")
def set_status(bid: int, body: StatusIn, user: User = Depends(require("soilcenter.work")), db: Session = Depends(get_db)):
    c = _center(db, user)
    b = db.get(SoilTestBooking, bid)
    if not b or b.center_id != c.id:
        raise HTTPException(404, "Booking not found")
    if b.status in (SoilBookingStatus.CANCELLED, SoilBookingStatus.REPORT_READY):
        raise HTTPException(409, "Booking is closed")
    if body.status != SoilBookingStatus.CANCELLED and ORDER.index(body.status) != ORDER.index(b.status) + 1:
        raise HTTPException(409, "Move one step at a time")
    b.status = body.status
    notify(db, b.user_id, "SOIL_BOOKING", f"Soil test {body.status.value.replace('_', ' ').lower()}", b.tracking_code, dedupe_key=f"sb{b.id}{body.status.value}")
    db.commit()
    return {"ok": True}


class ResultIn(BaseModel):
    soil_type: str | None = None
    ph: float | None = F(default=None, ge=0, le=14)
    nitrogen: float | None = F(default=None, ge=0, le=5000)
    phosphorus: float | None = F(default=None, ge=0, le=500)
    potassium: float | None = F(default=None, ge=0, le=5000)
    organic_carbon: float | None = F(default=None, ge=0, le=20)
    ec: float | None = F(default=None, ge=0, le=50)
    interpretation: str | None = F(default=None, max_length=3000)


@router.post("/bookings/{bid}/result")
def submit_result(bid: int, body: ResultIn, user: User = Depends(require("soilcenter.work")), db: Session = Depends(get_db)):
    """Saves lab values as a SoilReading on the farmer's farm and marks the report ready."""
    c = _center(db, user)
    b = db.get(SoilTestBooking, bid)
    if not b or b.center_id != c.id:
        raise HTTPException(404, "Booking not found")
    if b.status not in (SoilBookingStatus.IN_TESTING, SoilBookingStatus.SAMPLE_COLLECTED):
        raise HTTPException(409, "Result can be entered once the sample is collected")
    vals = body.model_dump(exclude={"interpretation"})
    db.add(SoilReading(user_id=b.user_id, farm_id=b.farm_id, field_id=b.field_id, on_date=date.today(), source="LAB", booking_id=b.id, **vals))
    b.interpretation = body.interpretation
    b.status = SoilBookingStatus.REPORT_READY
    notify(db, b.user_id, "SOIL_BOOKING", "Your soil test report is ready", b.tracking_code, sms=True)
    db.commit()
    return {"ok": True}
