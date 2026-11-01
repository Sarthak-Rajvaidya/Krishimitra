"""Supplier portal: own products and stock, incoming orders, earnings, customer inquiries."""
import re
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field as F
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require
from app.api.v1.common import page_args, stock_map
from app.api.v1.shop import order_out
from app.core.audit import audit
from app.db.base import utcnow
from app.db.session import get_db
from app.models import (Inquiry, InventoryBalance, InventoryTransaction, InvTxnType, Order, OrderItem, OrderStatus, Product,
                        ProductCategory, ProductType, Rating, User, WalletTxn)
from app.services import checkout as co
from app.services.notify import notify, notify_role
from app.services.wallet import get_wallet
from app.models import RoleName

router = APIRouter(prefix="/supplier", tags=["supplier"])
Sup = Depends(require("supplier.manage"))


class ProductIn(BaseModel):
    name: str = F(min_length=2, max_length=200)
    category_slug: str
    product_type: ProductType
    brand: str | None = F(default=None, max_length=80)
    description: str = F(default="", max_length=4000)
    pack_size: str = F(max_length=40)
    unit_qty: float = F(default=1, gt=0)
    unit: str = F(default="kg", max_length=10)
    price_rupees: float = F(gt=0, le=10000000)
    gst_rate_bp: int = F(default=500, ge=0, le=2800)
    crops: str = F(default="", max_length=255)
    use_tags: str = F(default="", max_length=255)
    safety_info: str = F(default="", max_length=2000)
    images: list[str] | None = None
    specs: dict | None = None
    initial_stock: int = F(default=0, ge=0, le=1000000)


def _slug(s: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", s.upper())[:8] or "ITEM"


def _own(db: Session, user: User, pid: int) -> Product:
    p = db.get(Product, pid)
    if not p or p.supplier_id != user.id or p.deleted_at:
        raise HTTPException(404, "Product not found")
    return p


def _row(p: Product, stock: int) -> dict:
    return {"id": p.id, "sku": p.sku, "name": p.name, "brand": p.brand, "category": p.category.slug, "price_paise": p.price_paise,
            "pack_size": p.pack_size, "stock": stock, "approval_status": p.approval_status, "approval_note": p.approval_note,
            "is_active": p.is_active, "rating_avg": p.rating_avg, "rating_count": p.rating_count}


@router.get("/products")
def my_products(page: int = 1, size: int = 50, user: User = Sup, db: Session = Depends(get_db)):
    off, size = page_args(page, size)
    ps = db.scalars(select(Product).where(Product.supplier_id == user.id, Product.deleted_at.is_(None)).order_by(Product.id.desc())
                    .offset(off).limit(size)).unique().all()
    st = stock_map(db, [p.id for p in ps])
    return [_row(p, st.get(p.id, 0)) for p in ps]


@router.post("/products", status_code=201)
def add_product(body: ProductIn, user: User = Sup, db: Session = Depends(get_db)):
    cat = db.scalar(select(ProductCategory).where(ProductCategory.slug == body.category_slug))
    if not cat:
        raise HTTPException(422, "Unknown category")
    d = body.model_dump(exclude={"category_slug", "price_rupees", "initial_stock"})
    p = Product(sku=f"S{user.id}-{_slug(body.name)}-{utcnow():%y%m%d%H%M%S}", category_id=cat.id, supplier_id=user.id,
                price_paise=round(body.price_rupees * 100), cost_paise=0, approval_status="PENDING", **d)
    db.add(p)
    db.flush()
    loc = co.supplier_location(db, user.id)
    db.add(InventoryBalance(product_id=p.id, location_id=loc.id, on_hand=body.initial_stock, reserved=0))
    if body.initial_stock:
        db.add(InventoryTransaction(product_id=p.id, location_id=loc.id, txn_type=InvTxnType.RECEIPT, quantity_delta=body.initial_stock,
                                    reference="initial", actor_user_id=user.id, created_at=utcnow()))
    notify_role(db, RoleName.ADMIN, "APPROVAL", "Product awaiting approval", p.name)
    audit(db, user.id, "supplier.product_add", "product", p.id)
    db.commit()
    return _row(p, body.initial_stock)


class ProductEdit(BaseModel):
    price_rupees: float | None = F(default=None, gt=0, le=10000000)
    description: str | None = F(default=None, max_length=4000)
    is_active: bool | None = None


@router.patch("/products/{pid}")
def edit_product(pid: int, body: ProductEdit, user: User = Sup, db: Session = Depends(get_db)):
    p = _own(db, user, pid)
    if body.price_rupees is not None:
        p.price_paise = round(body.price_rupees * 100)
    if body.description is not None:
        p.description = body.description
    if body.is_active is not None:
        p.is_active = body.is_active
    db.commit()
    return _row(p, stock_map(db, [p.id]).get(p.id, 0))


class StockIn(BaseModel):
    delta: int = F(ge=-1000000, le=1000000)
    note: str | None = F(default=None, max_length=200)


@router.post("/products/{pid}/stock")
def adjust_stock(pid: int, body: StockIn, user: User = Sup, db: Session = Depends(get_db)):
    p = _own(db, user, pid)
    loc = co.supplier_location(db, user.id)
    bal = db.scalar(select(InventoryBalance).where(InventoryBalance.product_id == p.id, InventoryBalance.location_id == loc.id).with_for_update())
    if not bal:
        bal = InventoryBalance(product_id=p.id, location_id=loc.id, on_hand=0, reserved=0)
        db.add(bal)
        db.flush()
    if bal.on_hand + body.delta < bal.reserved:
        raise HTTPException(409, "Stock cannot go below reserved quantity")
    bal.on_hand += body.delta
    db.add(InventoryTransaction(product_id=p.id, location_id=loc.id, txn_type=InvTxnType.ADJUSTMENT, quantity_delta=body.delta,
                                note=body.note, actor_user_id=user.id, created_at=utcnow()))
    db.commit()
    return {"stock": bal.on_hand - bal.reserved}


@router.get("/orders")
def my_orders(status: OrderStatus | None = None, page: int = 1, size: int = 30, user: User = Sup, db: Session = Depends(get_db)):
    off, size = page_args(page, size)
    q = select(Order).where(Order.supplier_id == user.id).order_by(Order.id.desc()).offset(off).limit(size)
    if status:
        q = q.where(Order.status == status)
    return [order_out(o) for o in db.scalars(q)]


class SupStatus(BaseModel):
    status: OrderStatus
    note: str | None = F(default=None, max_length=200)


@router.post("/orders/{oid}/status")
def order_status(oid: int, body: SupStatus, user: User = Sup, db: Session = Depends(get_db)):
    o = db.get(Order, oid)
    if not o or o.supplier_id != user.id:
        raise HTTPException(404, "Order not found")
    if body.status not in (OrderStatus.CONFIRMED, OrderStatus.PACKED, OrderStatus.READY_FOR_DISPATCH, OrderStatus.REJECTED):
        raise HTTPException(422, "Allowed: CONFIRMED, PACKED, READY_FOR_DISPATCH, REJECTED")
    return order_out(co.set_status(db, o, body.status, user, body.note))


@router.get("/analytics")
def analytics(days: int = 30, user: User = Sup, db: Session = Depends(get_db)):
    days = max(1, min(days, 365))
    since = utcnow() - timedelta(days=days)
    live = (Order.supplier_id == user.id, Order.placed_at >= since)
    by_status = dict(db.execute(select(Order.status, func.count(Order.id)).where(*live).group_by(Order.status)).all())
    sales = db.scalar(select(func.coalesce(func.sum(Order.subtotal_paise - Order.discount_paise), 0))
                      .where(*live, Order.status == OrderStatus.DELIVERED))
    top = db.execute(select(OrderItem.name_snapshot, func.sum(OrderItem.quantity).label("q")).join(Order, Order.id == OrderItem.order_id)
                     .where(*live, Order.status != OrderStatus.CANCELLED).group_by(OrderItem.name_snapshot).order_by(func.sum(OrderItem.quantity).desc()).limit(5)).all()
    low = db.execute(select(Product.name, InventoryBalance.on_hand - InventoryBalance.reserved)
                     .join(InventoryBalance, InventoryBalance.product_id == Product.id)
                     .where(Product.supplier_id == user.id, InventoryBalance.on_hand - InventoryBalance.reserved <= InventoryBalance.reorder_threshold).limit(10)).all()
    w = get_wallet(db, user.id)
    rating = db.execute(select(func.coalesce(func.avg(Rating.rating), 0), func.count(Rating.id))
                        .where(Rating.target_type == "SUPPLIER", Rating.target_id == user.id, Rating.status == "PUBLISHED")).one()
    return {"days": days, "orders_by_status": {k.value: v for k, v in by_status.items()}, "delivered_sales_paise": int(sales),
            "top_products": [{"name": n, "units": int(q)} for n, q in top], "low_stock": [{"name": n, "available": int(a)} for n, a in low],
            "wallet_balance_paise": w.balance_paise, "rating_avg": round(float(rating[0]), 2), "rating_count": rating[1]}


@router.get("/earnings")
def earnings(page: int = 1, size: int = 30, user: User = Sup, db: Session = Depends(get_db)):
    off, size = page_args(page, size)
    rows = db.scalars(select(WalletTxn).where(WalletTxn.user_id == user.id).order_by(WalletTxn.id.desc()).offset(off).limit(size))
    return {"balance_paise": get_wallet(db, user.id).balance_paise,
            "entries": [{"kind": t.kind, "amount_paise": t.amount_paise, "reference": t.reference, "at": t.created_at.isoformat()} for t in rows]}


@router.get("/inquiries")
def inquiries(user: User = Sup, db: Session = Depends(get_db)):
    rows = db.execute(select(Inquiry, User.full_name).join(User, User.id == Inquiry.farmer_id).where(Inquiry.supplier_id == user.id)
                      .order_by(Inquiry.id.desc()).limit(100)).all()
    return [{"id": i.id, "farmer": n, "product_id": i.product_id, "message": i.message, "reply": i.reply, "status": i.status,
             "at": i.created_at.isoformat()} for i, n in rows]


class ReplyIn(BaseModel):
    reply: str = F(min_length=1, max_length=600)


@router.post("/inquiries/{iid}/reply")
def reply(iid: int, body: ReplyIn, user: User = Sup, db: Session = Depends(get_db)):
    i = db.get(Inquiry, iid)
    if not i or i.supplier_id != user.id:
        raise HTTPException(404, "Inquiry not found")
    i.reply, i.status = body.reply, "ANSWERED"
    notify(db, i.farmer_id, "INQUIRY", "A supplier replied to your question", body.reply[:120])
    db.commit()
    return {"ok": True}


# ---------------- returns on my orders ----------------
@router.get("/returns")
def my_returns(user: User = Sup, db: Session = Depends(get_db)):
    from app.models import ReturnRequest
    rows = db.execute(select(ReturnRequest, Order.order_number).join(Order, Order.id == ReturnRequest.order_id)
                      .where(Order.supplier_id == user.id).order_by(ReturnRequest.id.desc()).limit(100)).all()
    return [{"id": r.id, "order": n, "reason": r.reason, "status": r.status, "refund_paise": r.refund_paise} for r, n in rows]


class DecideIn(BaseModel):
    approve: bool
    note: str | None = F(default=None, max_length=300)


@router.post("/returns/{rid}/decide")
def decide_return(rid: int, body: DecideIn, user: User = Sup, db: Session = Depends(get_db)):
    from app.models import ReturnRequest
    from app.services.returns import decide_return as do
    r = db.get(ReturnRequest, rid)
    o = db.get(Order, r.order_id) if r else None
    if not r or not o or o.supplier_id != user.id:
        raise HTTPException(404, "Return not found")
    do(db, r, body.approve, user, body.note)
    return {"status": r.status}
