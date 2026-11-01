"""Farmer-side marketplace extras: wishlist, reviews, supplier inquiries, returns, wallet, machinery rental."""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field as F
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require
from app.api.v1.common import page_args, product_out, stock_map
from app.core.audit import audit
from app.core.config import get_settings
from app.core.ratelimit import rate_limit
from app.db.base import as_utc, utcnow
from app.db.session import get_db
from app.models import (BookingStatus, Inquiry, Machine, MachineBooking, Order, OrderItem, OrderStatus, Product, Rating, ReturnRequest,
                        SupplierProfile, User, Wishlist, WalletTxn, ExpertProfile)
from app.services import payments, wallet
from app.services.notify import notify

router = APIRouter(tags=["market"])
Shop = Depends(require("shop.use"))


# ---------------- wishlist ----------------
@router.get("/wishlist")
def get_wishlist(user: User = Shop, db: Session = Depends(get_db)):
    ps = db.scalars(select(Product).join(Wishlist, Wishlist.product_id == Product.id).where(Wishlist.user_id == user.id).limit(200)).unique().all()
    st = stock_map(db, [p.id for p in ps])
    return [product_out(p, st.get(p.id, 0)) for p in ps]


@router.put("/wishlist/{pid}")
def add_wish(pid: int, user: User = Shop, db: Session = Depends(get_db)):
    if not db.get(Product, pid):
        raise HTTPException(404, "Product not found")
    if not db.scalar(select(Wishlist.id).where(Wishlist.user_id == user.id, Wishlist.product_id == pid)):
        db.add(Wishlist(user_id=user.id, product_id=pid, created_at=utcnow()))
        db.commit()
    return {"ok": True}


@router.delete("/wishlist/{pid}")
def remove_wish(pid: int, user: User = Shop, db: Session = Depends(get_db)):
    w = db.scalar(select(Wishlist).where(Wishlist.user_id == user.id, Wishlist.product_id == pid))
    if w:
        db.delete(w)
        db.commit()
    return {"ok": True}


# ---------------- ratings & reviews ----------------
TARGETS = ("PRODUCT", "SUPPLIER", "EXPERT", "MACHINE", "DELIVERY")


class RatingIn(BaseModel):
    target_type: str = F(pattern="^(PRODUCT|SUPPLIER|EXPERT|MACHINE|DELIVERY)$")
    target_id: int
    ref_id: int = 0                        # order / appointment / booking this review is about
    rating: int = F(ge=1, le=5)
    comment: str = F(default="", max_length=1000)


def _verified(db: Session, user: User, t: str, tid: int, ref: int) -> bool:
    """A review is 'verified' only when the reviewer really bought / used the thing."""
    if t == "PRODUCT":
        return bool(db.scalar(select(Order.id).join(OrderItem, OrderItem.order_id == Order.id)
                              .where(Order.user_id == user.id, OrderItem.product_id == tid, Order.status == OrderStatus.DELIVERED).limit(1)))
    if t == "SUPPLIER":
        return bool(db.scalar(select(Order.id).where(Order.user_id == user.id, Order.supplier_id == tid, Order.status == OrderStatus.DELIVERED).limit(1)))
    if t == "MACHINE":
        return bool(db.scalar(select(MachineBooking.id).where(MachineBooking.renter_id == user.id, MachineBooking.machine_id == tid,
                                                              MachineBooking.status == BookingStatus.COMPLETED).limit(1)))
    return False


def _refresh_aggregate(db: Session, t: str, tid: int) -> None:
    avg, n = db.execute(select(func.coalesce(func.avg(Rating.rating), 0), func.count(Rating.id))
                        .where(Rating.target_type == t, Rating.target_id == tid, Rating.status == "PUBLISHED")).one()
    avg = round(float(avg), 2)
    tgt = {"PRODUCT": (Product, Product.id), "MACHINE": (Machine, Machine.id), "SUPPLIER": (SupplierProfile, SupplierProfile.user_id),
           "EXPERT": (ExpertProfile, ExpertProfile.user_id)}.get(t)
    if tgt:
        db.execute(update(tgt[0]).where(tgt[1] == tid).values(rating_avg=avg, rating_count=n))


@router.post("/ratings", status_code=201)
def rate(body: RatingIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rate_limit(f"rate:{user.id}", 20)
    if body.target_id == user.id and body.target_type != "PRODUCT":
        raise HTTPException(403, "You cannot rate yourself")
    r = db.scalar(select(Rating).where(Rating.user_id == user.id, Rating.target_type == body.target_type,
                                       Rating.target_id == body.target_id, Rating.ref_id == body.ref_id))
    if r:
        r.rating, r.comment = body.rating, body.comment
    else:
        r = Rating(user_id=user.id, target_type=body.target_type, target_id=body.target_id, ref_id=body.ref_id, rating=body.rating,
                   comment=body.comment, verified=_verified(db, user, body.target_type, body.target_id, body.ref_id), is_demo=user.is_demo)
        db.add(r)
    db.flush()
    _refresh_aggregate(db, body.target_type, body.target_id)
    db.commit()
    return {"id": r.id, "verified": r.verified}


@router.get("/ratings")
def list_ratings(target_type: str = Query(pattern="^(PRODUCT|SUPPLIER|EXPERT|MACHINE|DELIVERY)$"), target_id: int = 0, page: int = 1, size: int = 20,
                 db: Session = Depends(get_db)):
    off, size = page_args(page, size)
    rows = db.execute(select(Rating, User.full_name).join(User, User.id == Rating.user_id)
                      .where(Rating.target_type == target_type, Rating.target_id == target_id, Rating.status == "PUBLISHED")
                      .order_by(Rating.id.desc()).offset(off).limit(size)).all()
    return [{"id": r.id, "rating": r.rating, "comment": r.comment, "verified": r.verified, "by": n.split()[0], "at": r.created_at.isoformat()} for r, n in rows]


# ---------------- supplier inquiry ----------------
class InquiryIn(BaseModel):
    supplier_id: int
    product_id: int | None = None
    message: str = F(min_length=3, max_length=600)


@router.post("/inquiries", status_code=201)
def contact_supplier(body: InquiryIn, user: User = Shop, db: Session = Depends(get_db)):
    rate_limit(f"inq:{user.id}", 10)
    if not db.scalar(select(SupplierProfile.id).where(SupplierProfile.user_id == body.supplier_id)):
        raise HTTPException(404, "Supplier not found")
    i = Inquiry(farmer_id=user.id, supplier_id=body.supplier_id, product_id=body.product_id, message=body.message)
    db.add(i)
    notify(db, body.supplier_id, "INQUIRY", f"Question from {user.full_name.split()[0]}", body.message[:120], sms=True)
    db.commit()
    return {"id": i.id}


@router.get("/inquiries")
def my_inquiries(user: User = Shop, db: Session = Depends(get_db)):
    rows = db.scalars(select(Inquiry).where(Inquiry.farmer_id == user.id).order_by(Inquiry.id.desc()).limit(50))
    return [{"id": i.id, "supplier_id": i.supplier_id, "message": i.message, "reply": i.reply, "status": i.status} for i in rows]


# ---------------- returns ----------------
RETURN_WINDOW_DAYS = 7


class ReturnIn(BaseModel):
    reason: str = F(min_length=5, max_length=300)


@router.post("/orders/{oid}/return", status_code=201)
def request_return(oid: int, body: ReturnIn, user: User = Shop, db: Session = Depends(get_db)):
    o = db.get(Order, oid)
    if not o or o.user_id != user.id:
        raise HTTPException(404, "Order not found")
    if o.status != OrderStatus.DELIVERED:
        raise HTTPException(409, "Only delivered orders can be returned")
    delivered_at = max((as_utc(h.created_at) for h in o.history if h.status == OrderStatus.DELIVERED), default=as_utc(o.placed_at))
    if utcnow() - delivered_at > timedelta(days=RETURN_WINDOW_DAYS):
        raise HTTPException(409, f"Return window of {RETURN_WINDOW_DAYS} days has passed")
    if db.scalar(select(ReturnRequest.id).where(ReturnRequest.order_id == oid)):
        raise HTTPException(409, "A return was already requested for this order")
    r = ReturnRequest(order_id=oid, user_id=user.id, reason=body.reason)
    db.add(r)
    o.status = OrderStatus.RETURN_REQUESTED
    if o.supplier_id:
        notify(db, o.supplier_id, "RETURN", "Return requested", o.order_number)
    db.commit()
    return {"id": r.id, "status": r.status}


@router.get("/returns")
def my_returns(user: User = Shop, db: Session = Depends(get_db)):
    return [{"id": r.id, "order_id": r.order_id, "status": r.status, "reason": r.reason, "note": r.decision_note, "refund_paise": r.refund_paise}
            for r in db.scalars(select(ReturnRequest).where(ReturnRequest.user_id == user.id).order_by(ReturnRequest.id.desc()).limit(50))]


# ---------------- wallet ----------------
Wal = Depends(require("wallet.use"))


@router.get("/wallet")
def my_wallet(page: int = 1, size: int = 30, user: User = Wal, db: Session = Depends(get_db)):
    off, size = page_args(page, size)
    w = wallet.get_wallet(db, user.id)
    db.commit()
    rows = db.scalars(select(WalletTxn).where(WalletTxn.user_id == user.id).order_by(WalletTxn.id.desc()).offset(off).limit(size))
    return {"balance_paise": w.balance_paise, "provider": get_settings().payment_provider,
            "history": [{"kind": t.kind, "amount_paise": t.amount_paise, "balance_after_paise": t.balance_after_paise, "reference": t.reference,
                         "at": t.created_at.isoformat()} for t in rows]}


class TopupIn(BaseModel):
    amount_rupees: int = F(ge=10, le=50000)


@router.post("/wallet/topup")
def topup(body: TopupIn, user: User = Wal, db: Session = Depends(get_db)):
    rate_limit(f"topup:{user.id}", 10)
    return payments.create_topup(db, user.id, body.amount_rupees * 100)


class ConfirmIn(BaseModel):
    gateway_order_id: str
    payment_id: str = F(default="sim", max_length=80)
    signature: str | None = None


@router.post("/wallet/confirm")
def confirm(body: ConfirmIn, user: User = Wal, db: Session = Depends(get_db)):
    g = payments.confirm_topup(db, user.id, body.gateway_order_id, body.payment_id, body.signature)
    return {"status": g.status, "balance_paise": wallet.get_wallet(db, user.id).balance_paise}


# ---------------- machinery rental ----------------
CATEGORIES = ("TRACTOR", "HARVESTER", "ROTAVATOR", "CULTIVATOR", "SEED_DRILL", "SPRAYER", "THRESHER", "JCB", "PUMP", "OTHER")


def machine_out(m: Machine) -> dict:
    return {"id": m.id, "owner_id": m.owner_id, "category": m.category, "name": m.name, "description": m.description, "specs": m.specs,
            "district": m.district, "state": m.state, "hourly_paise": m.hourly_paise, "daily_paise": m.daily_paise,
            "is_available": m.is_available, "rating_avg": m.rating_avg, "rating_count": m.rating_count, "approval_status": m.approval_status}


@router.get("/machines")
def search_machines(category: str | None = None, district: str | None = None, max_daily_rupees: int | None = None, page: int = 1, size: int = 20,
                    db: Session = Depends(get_db)):
    q = select(Machine).where(Machine.approval_status == "APPROVED", Machine.is_available.is_(True), Machine.deleted_at.is_(None))
    if category:
        q = q.where(Machine.category == category.upper())
    if district:
        q = q.where(func.lower(Machine.district) == district.lower())
    if max_daily_rupees:
        q = q.where(Machine.daily_paise <= max_daily_rupees * 100)
    off, size = page_args(page, size)
    return [machine_out(m) for m in db.scalars(q.order_by(Machine.rating_avg.desc(), Machine.id).offset(off).limit(size))]


class MachineIn(BaseModel):
    category: str = F(pattern="^(TRACTOR|HARVESTER|ROTAVATOR|CULTIVATOR|SEED_DRILL|SPRAYER|THRESHER|JCB|PUMP|OTHER)$")
    name: str = F(min_length=2, max_length=160)
    description: str | None = F(default=None, max_length=2000)
    specs: dict | None = None
    district: str | None = None
    state: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    hourly_rupees: float | None = F(default=None, gt=0)
    daily_rupees: float | None = F(default=None, gt=0)


@router.post("/machines", status_code=201)
def list_machine(body: MachineIn, user: User = Depends(require("machine.manage")), db: Session = Depends(get_db)):
    if not (body.hourly_rupees or body.daily_rupees):
        raise HTTPException(422, "Set an hourly or daily rate")
    d = body.model_dump(exclude={"hourly_rupees", "daily_rupees"})
    m = Machine(owner_id=user.id, hourly_paise=round(body.hourly_rupees * 100) if body.hourly_rupees else None,
                daily_paise=round(body.daily_rupees * 100) if body.daily_rupees else None, approval_status="PENDING", is_demo=user.is_demo, **d)
    db.add(m)
    db.commit()
    return machine_out(m)


@router.get("/machines/mine")
def my_machines(user: User = Depends(require("machine.manage")), db: Session = Depends(get_db)):
    return [machine_out(m) for m in db.scalars(select(Machine).where(Machine.owner_id == user.id, Machine.deleted_at.is_(None)))]


@router.post("/machines/{mid}/availability")
def set_available(mid: int, available: bool, user: User = Depends(require("machine.manage")), db: Session = Depends(get_db)):
    m = db.get(Machine, mid)
    if not m or m.owner_id != user.id:
        raise HTTPException(404, "Machine not found")
    m.is_available = available
    db.commit()
    return {"ok": True}


class BookIn(BaseModel):
    machine_id: int
    start_at: datetime
    units: int = F(ge=1, le=60)
    rate_type: str = F(pattern="^(HOURLY|DAILY)$")
    note: str | None = F(default=None, max_length=300)


def _booking_out(b: MachineBooking, m: Machine | None = None) -> dict:
    return {"id": b.id, "machine_id": b.machine_id, "machine": m.name if m else None, "start_at": b.start_at.isoformat(), "end_at": b.end_at.isoformat(),
            "rate_type": b.rate_type, "units": b.units, "amount_paise": b.amount_paise, "status": b.status.value, "payment_status": b.payment_status}


@router.post("/machines/book", status_code=201)
def book_machine(body: BookIn, user: User = Depends(require("machine.rent")), db: Session = Depends(get_db)):
    m = db.get(Machine, body.machine_id)
    if not m or m.approval_status != "APPROVED" or not m.is_available or m.deleted_at:
        raise HTTPException(404, "Machine not available")
    if m.owner_id == user.id:
        raise HTTPException(403, "You cannot rent your own machine")
    rate = m.hourly_paise if body.rate_type == "HOURLY" else m.daily_paise
    if not rate:
        raise HTTPException(422, f"This machine has no {body.rate_type.lower()} rate")
    start = as_utc(body.start_at)
    if start < utcnow():
        raise HTTPException(422, "Start time must be in the future")
    end = start + (timedelta(hours=body.units) if body.rate_type == "HOURLY" else timedelta(days=body.units))
    clash = db.scalar(select(MachineBooking.id).where(MachineBooking.machine_id == m.id, MachineBooking.status == BookingStatus.ACCEPTED,
                                                      MachineBooking.start_at < end, MachineBooking.end_at > start).limit(1))
    if clash:
        raise HTTPException(409, "Machine is already booked for that time")
    b = MachineBooking(machine_id=m.id, renter_id=user.id, start_at=start, end_at=end, rate_type=body.rate_type, units=body.units,
                       amount_paise=rate * body.units, note=body.note, is_demo=user.is_demo)
    db.add(b)
    db.flush()
    notify(db, m.owner_id, "RENTAL", "New rental request", f"{m.name} - {user.full_name}", sms=True)
    db.commit()
    return _booking_out(b, m)


@router.get("/machines/bookings")
def my_bookings(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Rentals I made, and requests for machines I own."""
    mine = db.execute(select(MachineBooking, Machine).join(Machine, Machine.id == MachineBooking.machine_id)
                      .where(MachineBooking.renter_id == user.id).order_by(MachineBooking.id.desc()).limit(50)).all()
    incoming = db.execute(select(MachineBooking, Machine).join(Machine, Machine.id == MachineBooking.machine_id)
                          .where(Machine.owner_id == user.id).order_by(MachineBooking.id.desc()).limit(50)).all()
    return {"rentals": [_booking_out(b, m) for b, m in mine], "requests": [_booking_out(b, m) for b, m in incoming]}


class DecideIn(BaseModel):
    action: str = F(pattern="^(ACCEPT|REJECT|COMPLETE)$")


@router.post("/machines/bookings/{bid}/decide")
def decide(bid: int, body: DecideIn, user: User = Depends(require("machine.manage")), db: Session = Depends(get_db)):
    b = db.get(MachineBooking, bid)
    m = db.get(Machine, b.machine_id) if b else None
    if not b or not m or m.owner_id != user.id:
        raise HTTPException(404, "Booking not found")
    if body.action == "ACCEPT" and b.status == BookingStatus.REQUESTED:
        if db.scalar(select(MachineBooking.id).where(MachineBooking.machine_id == m.id, MachineBooking.status == BookingStatus.ACCEPTED,
                                                     MachineBooking.start_at < b.end_at, MachineBooking.end_at > b.start_at).limit(1)):
            raise HTTPException(409, "Overlaps another accepted booking")
        b.status = BookingStatus.ACCEPTED
        notify(db, b.renter_id, "RENTAL", "Rental accepted - please pay from your wallet", m.name, sms=True)
    elif body.action == "REJECT" and b.status == BookingStatus.REQUESTED:
        b.status = BookingStatus.REJECTED
        notify(db, b.renter_id, "RENTAL", "Rental request declined", m.name)
    elif body.action == "COMPLETE" and b.status == BookingStatus.ACCEPTED and b.payment_status == "PAID":
        b.status = BookingStatus.COMPLETED
        fee = b.amount_paise * get_settings().commission_bp // 10_000
        wallet.credit(db, m.owner_id, b.amount_paise - fee, "RENTAL_EARNING", f"MB{b.id}")
    else:
        raise HTTPException(409, "Action not possible in the booking's current state (completion needs a paid booking)")
    db.commit()
    return _booking_out(b, m)


@router.post("/machines/bookings/{bid}/pay")
def pay_booking(bid: int, user: User = Depends(require("machine.rent", "wallet.use")), db: Session = Depends(get_db)):
    b = db.get(MachineBooking, bid)
    if not b or b.renter_id != user.id:
        raise HTTPException(404, "Booking not found")
    if b.status != BookingStatus.ACCEPTED or b.payment_status != "UNPAID":
        raise HTTPException(409, "Nothing to pay for this booking")
    wallet.debit(db, user.id, b.amount_paise, "RENTAL_PAYMENT", f"MB{b.id}")
    b.payment_status = "PAID"
    audit(db, user.id, "rental.pay", "machine_booking", b.id)
    db.commit()
    return _booking_out(b)


@router.post("/machines/bookings/{bid}/cancel")
def cancel_booking(bid: int, user: User = Depends(require("machine.rent")), db: Session = Depends(get_db)):
    b = db.get(MachineBooking, bid)
    if not b or b.renter_id != user.id:
        raise HTTPException(404, "Booking not found")
    if b.status not in (BookingStatus.REQUESTED, BookingStatus.ACCEPTED) or as_utc(b.start_at) <= utcnow():
        raise HTTPException(409, "This booking can no longer be cancelled")
    if b.payment_status == "PAID":
        wallet.credit(db, user.id, b.amount_paise, "REFUND", f"MB{b.id}")
        b.payment_status = "REFUNDED"
    b.status = BookingStatus.CANCELLED
    db.commit()
    return _booking_out(b)
