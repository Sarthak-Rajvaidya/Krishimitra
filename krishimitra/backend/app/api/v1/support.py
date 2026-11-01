"""Notifications, support tickets / complaints / feedback, and the farmer dashboard summary."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field as F
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.deps import district_scope, get_current_user, is_global_staff, require
from app.api.v1.common import page_args
from app.core.audit import audit
from app.core.ratelimit import rate_limit
from app.db.base import utcnow
from app.db.session import get_db
from app.models import (Advisory, Appointment, Crop, CropStatus, Device, Farm, Notification, Order, OrderStatus, SchemeApplication, Ticket,
                        TicketMessage, User, Wallet)
from app.services.notify import notify, prefs_of

router = APIRouter(tags=["support"])


# ---------------- notifications ----------------
@router.get("/notifications")
def my_notifications(unread_only: bool = False, page: int = 1, size: int = 30, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    off, size = page_args(page, size)
    q = select(Notification).where(Notification.user_id == user.id).order_by(Notification.id.desc()).offset(off).limit(size)
    if unread_only:
        q = q.where(Notification.read_at.is_(None))
    unread = db.scalar(select(func.count(Notification.id)).where(Notification.user_id == user.id, Notification.read_at.is_(None)))
    return {"unread": unread, "items": [{"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "data": n.data, "read": bool(n.read_at),
                                         "at": n.created_at.isoformat()} for n in db.scalars(q)]}


@router.get("/notifications/count")
def unread_count(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"unread": db.scalar(select(func.count(Notification.id)).where(Notification.user_id == user.id, Notification.read_at.is_(None)))}


@router.post("/notifications/read")
def mark_read(ids: list[int] | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None)).values(read_at=utcnow())
    if ids:
        q = q.where(Notification.id.in_(ids[:200]))
    db.execute(q)
    db.commit()
    return {"ok": True, "prefs": prefs_of(user)}


# ---------------- tickets ----------------
class TicketIn(BaseModel):
    kind: str = F(default="TICKET", pattern="^(TICKET|COMPLAINT|FEEDBACK)$")
    category: str = F(pattern="^(ORDER|DELIVERY|PAYMENT|SUPPLIER|EXPERT|MACHINE|APP|IOT|OTHER)$")
    subject: str = F(min_length=3, max_length=200)
    message: str = F(min_length=3, max_length=2000)
    related_type: str | None = F(default=None, max_length=20)
    related_id: int | None = None


def t_out(t: Ticket) -> dict:
    return {"id": t.id, "kind": t.kind, "category": t.category, "subject": t.subject, "status": t.status, "priority": t.priority, "escalated": t.escalated,
            "resolution": t.resolution, "related_type": t.related_type, "related_id": t.related_id, "created_at": t.created_at.isoformat()}


@router.post("/tickets", status_code=201)
def open_ticket(body: TicketIn, user: User = Depends(require("support.use")), db: Session = Depends(get_db)):
    rate_limit(f"tix:{user.id}", 10, 3600)
    t = Ticket(user_id=user.id, district_id=user.district_id, kind=body.kind, category=body.category, subject=body.subject,
               related_type=body.related_type, related_id=body.related_id, priority="HIGH" if body.category in ("PAYMENT", "DELIVERY") else "NORMAL")
    db.add(t)
    db.flush()
    db.add(TicketMessage(ticket_id=t.id, sender_id=user.id, body=body.message, created_at=utcnow()))
    from app.models import RoleName
    from app.services.notify import notify_role
    notify_role(db, RoleName.ADMIN, "SUPPORT", f"New {body.kind.lower()}: {body.subject[:60]}", user.full_name, district_id=user.district_id)
    db.commit()
    return t_out(t)


@router.get("/tickets")
def my_tickets(user: User = Depends(require("support.use")), db: Session = Depends(get_db)):
    return [t_out(t) for t in db.scalars(select(Ticket).where(Ticket.user_id == user.id).order_by(Ticket.id.desc()).limit(100))]


def _visible(db: Session, user: User, tid: int) -> Ticket:
    t = db.get(Ticket, tid)
    if not t:
        raise HTTPException(404, "Ticket not found")
    if t.user_id == user.id:
        return t
    perms = {p.code for p in user.role.permissions}
    if "support.manage" in perms or "district.manage" in perms:
        sc = district_scope(user)
        if sc is None or t.district_id == sc:
            return t
    raise HTTPException(404, "Ticket not found")


@router.get("/tickets/{tid}")
def ticket_thread(tid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = _visible(db, user, tid)
    msgs = db.execute(select(TicketMessage, User.full_name).join(User, User.id == TicketMessage.sender_id).where(TicketMessage.ticket_id == t.id)
                      .order_by(TicketMessage.id)).all()
    return {**t_out(t), "messages": [{"from": n, "mine": m.sender_id == user.id, "body": m.body, "at": m.created_at.isoformat()} for m, n in msgs]}


class ReplyIn(BaseModel):
    body: str = F(min_length=1, max_length=2000)


@router.post("/tickets/{tid}/reply", status_code=201)
def reply(tid: int, body: ReplyIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = _visible(db, user, tid)
    if t.status == "CLOSED":
        raise HTTPException(409, "Ticket is closed")
    db.add(TicketMessage(ticket_id=t.id, sender_id=user.id, body=body.body, created_at=utcnow()))
    if user.id != t.user_id:
        if t.status == "OPEN":
            t.status = "IN_PROGRESS"
        notify(db, t.user_id, "SUPPORT", f"Reply on: {t.subject[:60]}", body.body[:120], dedupe_key=f"tix{t.id}", dedupe_hours=1)
    elif t.status in ("RESOLVED",):
        t.status = "OPEN"
    db.commit()
    return {"ok": True}


# ---------------- staff ticket handling ----------------
Staff = Depends(require("support.manage"))


@router.get("/admin/tickets")
def admin_tickets(status: str | None = None, escalated: bool | None = None, page: int = 1, size: int = 50, user: User = Staff, db: Session = Depends(get_db)):
    q = select(Ticket).order_by(Ticket.escalated.desc(), Ticket.id.desc())
    if status:
        q = q.where(Ticket.status == status.upper())
    if escalated is not None:
        q = q.where(Ticket.escalated == escalated)
    off, size = page_args(page, size)
    return [t_out(t) for t in db.scalars(q.offset(off).limit(size))]


class AssignIn(BaseModel):
    assigned_to: int | None = None
    status: str | None = F(default=None, pattern="^(OPEN|ASSIGNED|IN_PROGRESS|RESOLVED|CLOSED)$")
    escalate: bool | None = None
    resolution: str | None = F(default=None, max_length=500)


@router.patch("/admin/tickets/{tid}")
def admin_update(tid: int, body: AssignIn, user: User = Staff, db: Session = Depends(get_db)):
    t = db.get(Ticket, tid)
    if not t:
        raise HTTPException(404, "Ticket not found")
    if body.assigned_to:
        t.assigned_to = body.assigned_to
        t.status = "ASSIGNED" if t.status == "OPEN" else t.status
    if body.status:
        t.status = body.status
    if body.escalate is not None:
        t.escalated = body.escalate
    if body.resolution is not None:
        t.resolution = body.resolution
    if t.status in ("RESOLVED", "CLOSED"):
        notify(db, t.user_id, "SUPPORT", f"Ticket {t.status.lower()}: {t.subject[:60]}", t.resolution or "", dedupe_key=f"tixs{t.id}{t.status}")
    audit(db, user.id, "ticket.update", "ticket", t.id, {"status": t.status})
    db.commit()
    return t_out(t)


# ---------------- farmer dashboard ----------------
@router.get("/dashboard")
def dashboard(user: User = Depends(require("farm.manage")), db: Session = Depends(get_db)):
    """One call for the farmer home screen. Each number is a cheap indexed count."""
    uid = user.id
    one = lambda q: db.scalar(q)  # noqa: E731
    active_orders = one(select(func.count(Order.id)).where(Order.user_id == uid, Order.status.in_((OrderStatus.PLACED, OrderStatus.CONFIRMED, OrderStatus.PACKED,
                                                                                                     OrderStatus.READY_FOR_DISPATCH, OrderStatus.OUT_FOR_DELIVERY))))
    crops = db.scalars(select(Crop).where(Crop.user_id == uid, Crop.status == CropStatus.ACTIVE).order_by(Crop.expected_harvest_date).limit(20)).all()
    upcoming = [{"id": c.id, "name": c.name, "expected_harvest_date": c.expected_harvest_date} for c in crops if c.expected_harvest_date and c.expected_harvest_date <= date.today() + timedelta(days=30)]
    appts = db.scalars(select(Appointment).where(Appointment.farmer_id == uid, Appointment.status.in_(("REQUESTED", "CONFIRMED")), Appointment.scheduled_at >= utcnow())
                       .order_by(Appointment.scheduled_at).limit(3)).all()
    adv = db.scalars(select(Advisory).where(Advisory.user_id == uid, Advisory.read_at.is_(None)).order_by(Advisory.id.desc()).limit(5)).all()
    offline = one(select(func.count(Device.id)).where(Device.owner_id == uid, Device.is_active.is_(True), Device.connectivity == "OFFLINE"))
    bal = one(select(Wallet.balance_paise).where(Wallet.user_id == uid)) or 0
    return {"name": user.full_name, "farms": one(select(func.count(Farm.id)).where(Farm.user_id == uid, Farm.deleted_at.is_(None))),
            "active_crops": len(crops), "harvest_soon": upcoming, "active_orders": active_orders, "wallet_balance_paise": bal,
            "unread_notifications": one(select(func.count(Notification.id)).where(Notification.user_id == uid, Notification.read_at.is_(None))),
            "upcoming_appointments": [{"id": a.id, "at": a.scheduled_at.isoformat(), "topic": a.topic, "status": a.status} for a in appts],
            "advisories": [{"id": a.id, "severity": a.severity, "title": a.title, "category": a.category} for a in adv],
            "devices_offline": offline,
            "open_schemes": one(select(func.count(SchemeApplication.id)).where(SchemeApplication.user_id == uid, SchemeApplication.status == "PLANNED"))}


