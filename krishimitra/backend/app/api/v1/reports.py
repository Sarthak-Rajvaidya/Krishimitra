"""Report registry (JSON or CSV) and the district dashboard. District managers are always limited to their own district."""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics import metrics as M
from app.api.deps import district_scope, require_any
from app.api.v1.csvutil import csv_response
from app.core.audit import audit
from app.db.base import utcnow
from app.db.session import get_db
from app.models import (Crop, CropDiagnosis, Delivery, DeliveryStatus, Device, Machine, MachineBooking, Order, OrderStatus, Role, RoleName, SoilTestBooking, Ticket,
                        User, UserStatus)

router = APIRouter(tags=["reports"])
Rep = Depends(require_any("reports.admin", "reports.operational", "district.manage"))
CAP = 50000


def _users(db, s, e, sc):
    q = select(Role.name, User.status, func.count(User.id)).join(User, User.role_id == Role.id).where(User.created_at >= s, User.created_at < e).group_by(Role.name, User.status)
    if sc:
        q = q.where(User.district_id == sc)
    return ["role", "status", "new_users"], [[r.value, st.value, n] for r, st, n in db.execute(q)]


def _orders(db, s, e, sc):
    q = select(Order.ship_district, Order.status, func.count(Order.id), func.coalesce(func.sum(Order.total_paise), 0)).where(Order.placed_at >= s, Order.placed_at < e).group_by(Order.ship_district, Order.status)
    if sc:
        q = q.where(Order.district_id == sc)
    return ["district", "status", "orders", "value_paise"], [[d, st.value, n, int(v)] for d, st, n, v in db.execute(q)]


def _suppliers(db, s, e, sc):
    q = select(Order.supplier_id, func.count(Order.id), func.coalesce(func.sum(Order.subtotal_paise - Order.discount_paise), 0)) \
        .where(Order.placed_at >= s, Order.placed_at < e, Order.status == OrderStatus.DELIVERED, Order.supplier_id.is_not(None)).group_by(Order.supplier_id).order_by(func.sum(Order.subtotal_paise).desc()).limit(500)
    if sc:
        q = q.where(Order.district_id == sc)
    return ["supplier_id", "delivered_orders", "sales_paise"], [[a, n, int(v)] for a, n, v in db.execute(q)]


def _deliveries(db, s, e, sc):
    q = select(Delivery.status, func.count(Delivery.id)).join(Order, Order.id == Delivery.order_id).where(Delivery.created_at >= s, Delivery.created_at < e).group_by(Delivery.status)
    if sc:
        q = q.where(Order.district_id == sc)
    return ["status", "deliveries"], [[st.value, n] for st, n in db.execute(q)]


def _iot(db, s, e, sc):
    q = select(Device.connectivity, Device.health, func.count(Device.id)).where(Device.is_active.is_(True)).group_by(Device.connectivity, Device.health)
    if sc:
        q = q.join(User, User.id == Device.owner_id).where(User.district_id == sc)
    return ["connectivity", "health", "devices"], [[c, h, n] for c, h, n in db.execute(q)]


def _soil(db, s, e, sc):
    q = select(SoilTestBooking.status, func.count(SoilTestBooking.id)).where(SoilTestBooking.created_at >= s, SoilTestBooking.created_at < e).group_by(SoilTestBooking.status)
    if sc:
        q = q.join(User, User.id == SoilTestBooking.user_id).where(User.district_id == sc)
    return ["status", "bookings"], [[st.value, n] for st, n in db.execute(q)]


def _support(db, s, e, sc):
    q = select(Ticket.category, Ticket.status, func.count(Ticket.id)).where(Ticket.created_at >= s, Ticket.created_at < e).group_by(Ticket.category, Ticket.status)
    if sc:
        q = q.where(Ticket.district_id == sc)
    return ["category", "status", "tickets"], [[c, st, n] for c, st, n in db.execute(q)]


def _crops(db, s, e, sc):
    q = select(Crop.name, func.count(Crop.id), func.coalesce(func.sum(Crop.area_acres), 0)).where(Crop.status == "ACTIVE").group_by(Crop.name).order_by(func.count(Crop.id).desc()).limit(200)
    if sc:
        q = q.join(User, User.id == Crop.user_id).where(User.district_id == sc)
    return ["crop", "active_plantings", "acres"], [[n, c, round(float(a), 1)] for n, c, a in db.execute(q)]


def _diseases(db, s, e, sc):
    rows = M.crop_issue_frequency(db, s, e)
    return ["issue", "count"], [[r.get("label") or r.get("issue"), r.get("count")] for r in rows]


def _machines(db, s, e, sc):
    q = select(Machine.category, MachineBooking.status, func.count(MachineBooking.id)).join(Machine, Machine.id == MachineBooking.machine_id) \
        .where(MachineBooking.created_at >= s, MachineBooking.created_at < e).group_by(Machine.category, MachineBooking.status)
    return ["category", "status", "bookings"], [[c, st.value, n] for c, st, n in db.execute(q)]


REGISTRY = {
    "users": ("New users by role and status", "reports.admin", _users), "orders": ("Orders by district and status", "reports.operational", _orders),
    "suppliers": ("Delivered sales per supplier", "reports.admin", _suppliers), "deliveries": ("Deliveries by status", "reports.operational", _deliveries),
    "iot": ("IoT device health", "reports.admin", _iot), "soil-tests": ("Soil test bookings", "reports.operational", _soil),
    "support": ("Support tickets", "reports.operational", _support), "crops": ("Active crops across farmers", "reports.admin", _crops),
    "diseases": ("Most reported crop issues", "reports.admin", _diseases), "machinery": ("Machine rental bookings", "reports.admin", _machines),
}


@router.get("/reports")
def catalog(user: User = Rep):
    return [{"key": k, "title": v[0]} for k, v in REGISTRY.items()]


@router.get("/reports/{key}")
def run(key: str, range: str = "30d", start: str | None = None, end: str | None = None, format: str = Query("json", pattern="^(json|csv)$"),
        user: User = Rep, db: Session = Depends(get_db)):
    if key not in REGISTRY:
        raise HTTPException(404, "Unknown report")
    title, perm, fn = REGISTRY[key]
    perms = {p.code for p in user.role.permissions}
    if perm not in perms and "district.manage" not in perms and "reports.admin" not in perms:
        raise HTTPException(403, "Forbidden")
    s, e = M.parse_range(range, start, end)
    header, rows = fn(db, s, e, district_scope(user))
    rows = rows[:CAP]
    if format == "csv":
        audit(db, user.id, "report.export", None, None, {"report": key})
        db.commit()
        return csv_response(f"{key}.csv", header, rows)
    return {"title": title, "range": {"start": s.isoformat(), "end": e.isoformat()}, "columns": header, "rows": rows}


@router.get("/district/dashboard")
def district_dashboard(user: User = Depends(require_any("district.manage", "reports.operational")), db: Session = Depends(get_db)):
    sc = district_scope(user)
    since = utcnow() - timedelta(days=30)
    uq = lambda *c: db.scalar(select(func.count(User.id)).where(*c, *( [User.district_id == sc] if sc else [])))  # noqa: E731
    oq = lambda *c: db.scalar(select(func.count(Order.id)).where(*c, *( [Order.district_id == sc] if sc else [])))  # noqa: E731
    farmers = db.scalar(select(func.count(User.id)).join(Role, Role.id == User.role_id).where(Role.name == RoleName.FARMER, User.status == UserStatus.ACTIVE, *([User.district_id == sc] if sc else [])))
    open_tix = db.scalar(select(func.count(Ticket.id)).where(Ticket.status.in_(("OPEN", "ASSIGNED", "IN_PROGRESS")), *([Ticket.district_id == sc] if sc else [])))
    waiting = db.scalar(select(func.count(Delivery.id)).join(Order, Order.id == Delivery.order_id)
                        .where(Delivery.partner_id.is_(None), Delivery.status == DeliveryStatus.ASSIGNED, *([Order.district_id == sc] if sc else [])))
    return {"district_id": sc, "active_farmers": farmers, "pending_approvals": uq(User.status == UserStatus.PENDING_APPROVAL),
            "orders_30d": oq(Order.placed_at >= since), "orders_active": oq(Order.status.in_((OrderStatus.PLACED, OrderStatus.CONFIRMED, OrderStatus.PACKED, OrderStatus.READY_FOR_DISPATCH, OrderStatus.OUT_FOR_DELIVERY))),
            "deliveries_waiting_for_partner": waiting, "open_tickets": open_tix,
            "disease_reports_30d": db.scalar(select(func.count(CropDiagnosis.id)).where(CropDiagnosis.created_at >= since))}
