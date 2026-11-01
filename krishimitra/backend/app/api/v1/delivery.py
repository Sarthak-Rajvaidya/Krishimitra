"""Delivery partner app and admin assignment. Delivery is confirmed only with the farmer's OTP."""
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field as F
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import district_scope, require
from app.core.audit import audit
from app.core.security import hmac_code
from app.db.base import utcnow
from app.db.session import get_db
from app.models import (Delivery, DeliveryProfile, DeliveryStatus, Order, OrderStatus, OrderStatusHistory, RoleName, User, UserStatus, Role)
from app.services import checkout as co
from app.services import wallet
from app.services.notify import notify

router = APIRouter(prefix="/delivery", tags=["delivery"])
Partner = Depends(require("delivery.work"))
Staff = Depends(require("delivery.manage"))
MAX_OTP_TRIES = 5


def _job(d: Delivery, o: Order) -> dict:
    return {"id": d.id, "order_id": o.id, "order_number": o.order_number, "status": d.status.value, "fee_paise": d.fee_paise,
            "collect_cash_paise": o.total_paise if o.payment_mode.value == "COD" else 0,
            "drop": {"name": o.ship_name, "phone": o.ship_phone, "line1": o.ship_line1, "district": o.ship_district, "pincode": o.ship_pincode},
            "due_by": d.due_by.isoformat() if d.due_by else None, "items": sum(i.quantity for i in o.items)}


# ---------------- partner ----------------
@router.get("/jobs")
def my_jobs(active_only: bool = True, user: User = Partner, db: Session = Depends(get_db)):
    q = select(Delivery, Order).join(Order, Order.id == Delivery.order_id).where(Delivery.partner_id == user.id).order_by(Delivery.id.desc()).limit(100)
    if active_only:
        q = q.where(Delivery.status.in_((DeliveryStatus.ASSIGNED, DeliveryStatus.ACCEPTED, DeliveryStatus.PICKED_UP)))
    return [_job(d, o) for d, o in db.execute(q)]


def _mine(db: Session, user: User, did: int) -> tuple[Delivery, Order]:
    d = db.get(Delivery, did)
    if not d or d.partner_id != user.id:
        raise HTTPException(404, "Job not found")
    return d, db.get(Order, d.order_id)


@router.post("/jobs/{did}/accept")
def accept(did: int, user: User = Partner, db: Session = Depends(get_db)):
    d, o = _mine(db, user, did)
    if d.status != DeliveryStatus.ASSIGNED:
        raise HTTPException(409, "Job is not waiting for acceptance")
    d.status = DeliveryStatus.ACCEPTED
    db.commit()
    return _job(d, o)


@router.post("/jobs/{did}/reject")
def reject(did: int, user: User = Partner, db: Session = Depends(get_db)):
    d, o = _mine(db, user, did)
    if d.status != DeliveryStatus.ASSIGNED:
        raise HTTPException(409, "Job is not waiting for acceptance")
    d.status, d.partner_id = DeliveryStatus.ASSIGNED, None          # returns to the unassigned pool
    notify(db, user.id, "DELIVERY", "Job declined", o.order_number)
    from app.models import RoleName as _R
    from app.services.notify import notify_role
    notify_role(db, _R.ADMIN, "DELIVERY", "Delivery partner declined a job", o.order_number)
    db.commit()
    return {"ok": True}


@router.post("/jobs/{did}/pickup")
def pickup(did: int, user: User = Partner, db: Session = Depends(get_db)):
    """Partner collected the parcel from the supplier/warehouse. Generates the OTP the farmer will read out at the door."""
    d, o = _mine(db, user, did)
    if d.status != DeliveryStatus.ACCEPTED or o.status != OrderStatus.READY_FOR_DISPATCH:
        raise HTTPException(409, "Accept the job first; order must be ready for dispatch")
    code = f"{secrets.randbelow(10 ** 4):04d}"
    now = utcnow()
    d.otp_hash, d.otp_plain_for_farmer, d.otp_attempts = hmac_code(f"delivery{d.id}", "DELIVER", code), code, 0
    d.status, d.picked_up_at = DeliveryStatus.PICKED_UP, now
    o.status = OrderStatus.OUT_FOR_DELIVERY
    o.history.append(OrderStatusHistory(status=OrderStatus.OUT_FOR_DELIVERY, note="Out for delivery", actor_user_id=user.id, created_at=now))
    notify(db, o.user_id, "ORDER", "Your order is out for delivery", f"Delivery code: {code}. Share it only when you receive the parcel.",
           data={"order_id": o.id}, sms=True)
    db.commit()
    return _job(d, o)


class OtpIn(BaseModel):
    otp: str = F(min_length=4, max_length=4, pattern=r"^\d{4}$")


@router.post("/jobs/{did}/deliver")
def deliver(did: int, body: OtpIn, user: User = Partner, db: Session = Depends(get_db)):
    d, o = _mine(db, user, did)
    if d.status != DeliveryStatus.PICKED_UP or not d.otp_hash:
        raise HTTPException(409, "Parcel has not been picked up")
    if d.otp_attempts >= MAX_OTP_TRIES:
        raise HTTPException(423, "Too many wrong codes. Contact support")
    d.otp_attempts += 1
    if not secrets.compare_digest(d.otp_hash, hmac_code(f"delivery{d.id}", "DELIVER", body.otp)):
        db.commit()
        raise HTTPException(400, "Wrong code")
    d.status, d.delivered_at, d.otp_plain_for_farmer = DeliveryStatus.DELIVERED, utcnow(), None
    co.mark_delivered(db, o, user.id)
    wallet.credit(db, user.id, d.fee_paise, "DELIVERY_EARNING", o.order_number)
    audit(db, user.id, "delivery.complete", "order", o.id)
    db.commit()
    return _job(d, o)


class FailIn(BaseModel):
    reason: str = F(min_length=3, max_length=300)


@router.post("/jobs/{did}/fail")
def fail(did: int, body: FailIn, user: User = Partner, db: Session = Depends(get_db)):
    d, o = _mine(db, user, did)
    if d.status != DeliveryStatus.PICKED_UP:
        raise HTTPException(409, "Only a picked-up parcel can be marked undelivered")
    d.status, d.note, d.otp_plain_for_farmer = DeliveryStatus.FAILED, body.reason, None
    o.status = OrderStatus.READY_FOR_DISPATCH      # goes back to dispatch for re-assignment
    o.history.append(OrderStatusHistory(status=OrderStatus.READY_FOR_DISPATCH, note=f"Delivery failed: {body.reason}", actor_user_id=user.id, created_at=utcnow()))
    db.add(Delivery(order_id=o.id, fee_paise=d.fee_paise))
    notify(db, o.user_id, "ORDER", "Delivery attempt failed", f"{o.order_number}: {body.reason}")
    db.commit()
    return {"ok": True}


@router.get("/earnings")
def earnings(user: User = Partner, db: Session = Depends(get_db)):
    n, total = db.execute(select(func.count(Delivery.id), func.coalesce(func.sum(Delivery.fee_paise), 0))
                          .where(Delivery.partner_id == user.id, Delivery.status == DeliveryStatus.DELIVERED)).one()
    bal = wallet.get_wallet(db, user.id).balance_paise
    db.commit()
    return {"deliveries": n, "earned_paise": int(total), "wallet_balance_paise": bal}


# ---------------- admin / district manager ----------------
@router.get("/queue")
def queue(user: User = Staff, db: Session = Depends(get_db)):
    """Orders waiting for a partner."""
    q = select(Delivery, Order).join(Order, Order.id == Delivery.order_id).where(Delivery.partner_id.is_(None), Delivery.status == DeliveryStatus.ASSIGNED)
    sc = district_scope(user)
    if sc:
        q = q.where(Order.district_id == sc)
    return [_job(d, o) for d, o in db.execute(q.order_by(Delivery.id).limit(200))]


@router.get("/partners")
def partners(user: User = Staff, db: Session = Depends(get_db)):
    q = select(User, DeliveryProfile).join(DeliveryProfile, DeliveryProfile.user_id == User.id) \
        .where(User.status == UserStatus.ACTIVE, User.role_id == select(Role.id).where(Role.name == RoleName.DELIVERY).scalar_subquery())
    sc = district_scope(user)
    if sc:
        q = q.where(User.district_id == sc)
    active = dict(db.execute(select(Delivery.partner_id, func.count(Delivery.id)).where(Delivery.status.in_((DeliveryStatus.ASSIGNED, DeliveryStatus.ACCEPTED, DeliveryStatus.PICKED_UP)))
                             .group_by(Delivery.partner_id)).all())
    return [{"id": u.id, "name": u.full_name, "phone": u.phone, "vehicle": p.vehicle_type, "active_jobs": active.get(u.id, 0)} for u, p in db.execute(q.limit(300))]


class AssignIn(BaseModel):
    partner_id: int
    hours: int = F(default=24, ge=1, le=168)


@router.post("/{did}/assign")
def assign(did: int, body: AssignIn, user: User = Staff, db: Session = Depends(get_db)):
    d = db.get(Delivery, did)
    if not d or d.status != DeliveryStatus.ASSIGNED:
        raise HTTPException(404, "Delivery not found or already moving")
    o = db.get(Order, d.order_id)
    sc = district_scope(user)
    if sc and o.district_id != sc:
        raise HTTPException(404, "Delivery not found")
    p = db.get(User, body.partner_id)
    if not p or p.role.name != RoleName.DELIVERY or p.status != UserStatus.ACTIVE:
        raise HTTPException(422, "Choose an approved delivery partner")
    d.partner_id, d.assigned_at, d.due_by = p.id, utcnow(), utcnow() + timedelta(hours=body.hours)
    notify(db, p.id, "DELIVERY", "New delivery assigned", f"{o.order_number} to {o.ship_district}", sms=True)
    audit(db, user.id, "delivery.assign", "delivery", d.id, {"partner": p.id})
    db.commit()
    return _job(d, o)
