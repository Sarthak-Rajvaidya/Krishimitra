import csv
import io

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics import metrics as M
from app.api.deps import district_scope, require, require_any
from app.api.v1.common import page_args, product_out, stock_map
from app.api.v1.csvutil import csv_response
from app.api.v1.shop import order_out
from app.core.audit import audit
from app.db.base import utcnow
from app.db.session import get_db
from app.models import (AuditLog, InventoryBalance, InventoryLocation, InventoryTransaction, InvTxnType, Order,
                        OrderStatus, Product, ProductCategory, ProductType, Promotion, Role, RoleName, User)
from app.services import checkout as co

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/overview")
def overview(range: str = "30d", start: str | None = None, end: str | None = None,
             user: User = Depends(require("reports.operational")), db: Session = Depends(get_db)):
    s, e = M.parse_range(range, start, end)
    inv = M.inventory_overview(db, s, e)
    return {"range": {"start": s.isoformat(), "end": e.isoformat()}, "orders": M.order_summary(db, s, e),
            "finance": {k: v for k, v in M.finance_summary(db, s, e).items() if k in ("net_sales_paise", "refunds_paise")},
            "total_products": db.scalar(select(func.count(Product.id)).where(Product.deleted_at.is_(None))),
            "low_stock_count": len(inv["low_stock"]), "low_stock": inv["low_stock"], "inventory_levels": inv["levels"],
            "sales_daily": M.sales_series(db, s, e, "day"), "sales_monthly": M.sales_series(db, s, e, "month"),
            "category_sales": M.category_sales(db, s, e), "top_products": M.top_products(db, s, e)}


# ---------- products ----------
class ProductIn(BaseModel):
    sku: str = Field(min_length=2, max_length=40)
    name: str = Field(min_length=2, max_length=200)
    category_slug: str
    product_type: ProductType
    description: str = ""
    pack_size: str
    unit_qty: float = Field(1, gt=0)
    unit: str = "kg"
    price_paise: int = Field(ge=0)
    cost_paise: int = Field(0, ge=0)
    gst_rate_bp: int = Field(500, ge=0, le=2800)
    image_url: str | None = None
    crops: str = ""
    use_tags: str = ""
    safety_info: str = ""
    is_active: bool = True


def _apply(p: Product, body: ProductIn, db: Session) -> None:
    cat = db.scalar(select(ProductCategory).where(ProductCategory.slug == body.category_slug))
    if not cat:
        raise HTTPException(422, "Unknown category")
    for k, v in body.model_dump(exclude={"category_slug"}).items():
        setattr(p, k, v)
    p.category_id = cat.id


@router.get("/products")
def admin_products(q: str | None = None, approval: str | None = None, page: int = 1, size: int = 50,
                   user: User = Depends(require("catalog.manage")), db: Session = Depends(get_db)):
    stmt = select(Product).where(Product.deleted_at.is_(None)).order_by(Product.id.desc())
    if q:
        stmt = stmt.where(func.lower(Product.name).like(f"%{q.lower()}%") | func.lower(Product.sku).like(f"%{q.lower()}%"))
    if approval:
        stmt = stmt.where(Product.approval_status == approval.upper())
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    off, size = page_args(page, size)
    rows = db.scalars(stmt.offset(off).limit(size)).unique().all()
    st = stock_map(db, [p.id for p in rows])
    return {"total": total, "items": [{**product_out(p, st.get(p.id, 0)), "cost_paise": p.cost_paise, "is_active": p.is_active, "supplier_id": p.supplier_id,
                                       "approval_status": p.approval_status} for p in rows]}


class Approval(BaseModel):
    approve: bool
    note: str | None = Field(default=None, max_length=300)


@router.post("/products/{pid}/approval")
def approve_product(pid: int, body: Approval, user: User = Depends(require("approvals.manage")), db: Session = Depends(get_db)):
    from app.services.notify import notify
    p = db.get(Product, pid)
    if not p or p.deleted_at:
        raise HTTPException(404, "Product not found")
    p.approval_status, p.approval_note = ("APPROVED" if body.approve else "REJECTED"), body.note
    if p.supplier_id:
        notify(db, p.supplier_id, "APPROVAL", f"Product {'approved' if body.approve else 'rejected'}: {p.name[:60]}", body.note or "")
    audit(db, user.id, "product.approval", "product", pid, {"approve": body.approve})
    db.commit()
    return {"ok": True}


@router.get("/machines")
def machines(approval: str = "PENDING", user: User = Depends(require("approvals.manage")), db: Session = Depends(get_db)):
    from app.models import Machine
    rows = db.scalars(select(Machine).where(Machine.approval_status == approval.upper(), Machine.deleted_at.is_(None)).order_by(Machine.id).limit(100))
    return [{"id": m.id, "owner_id": m.owner_id, "name": m.name, "category": m.category, "district": m.district, "daily_paise": m.daily_paise, "hourly_paise": m.hourly_paise} for m in rows]


@router.post("/machines/{mid}/approval")
def approve_machine(mid: int, body: Approval, user: User = Depends(require("approvals.manage")), db: Session = Depends(get_db)):
    from app.models import Machine
    from app.services.notify import notify
    m = db.get(Machine, mid)
    if not m:
        raise HTTPException(404, "Machine not found")
    m.approval_status = "APPROVED" if body.approve else "REJECTED"
    notify(db, m.owner_id, "APPROVAL", f"Machine {'approved' if body.approve else 'rejected'}: {m.name[:60]}", body.note or "")
    audit(db, user.id, "machine.approval", "machine", mid, {"approve": body.approve})
    db.commit()
    return {"ok": True}


@router.post("/products", status_code=201)
def create_product(body: ProductIn, user: User = Depends(require("catalog.manage")), db: Session = Depends(get_db)):
    if db.scalar(select(Product).where(Product.sku == body.sku)):
        raise HTTPException(409, "SKU already exists")
    p = Product()
    _apply(p, body, db)
    db.add(p)
    db.flush()
    loc = co.platform_location(db)
    db.add(InventoryBalance(product_id=p.id, location_id=loc.id, on_hand=0))
    audit(db, user.id, "product.create", "product", p.id, {"sku": p.sku})
    db.commit()
    return {"id": p.id}


@router.put("/products/{pid}")
def update_product(pid: int, body: ProductIn, user: User = Depends(require("catalog.manage")), db: Session = Depends(get_db)):
    p = db.get(Product, pid)
    if not p or p.deleted_at:
        raise HTTPException(404, "Product not found")
    before = {"price_paise": p.price_paise, "is_active": p.is_active}
    _apply(p, body, db)
    audit(db, user.id, "product.update", "product", pid, {"before": before, "after": {"price_paise": p.price_paise, "is_active": p.is_active}})
    db.commit()
    return {"ok": True}


@router.delete("/products/{pid}")
def delete_product(pid: int, user: User = Depends(require("catalog.manage")), db: Session = Depends(get_db)):
    p = db.get(Product, pid)
    if not p or p.deleted_at:
        raise HTTPException(404, "Product not found")
    p.deleted_at = utcnow()  # soft delete keeps order history intact
    p.is_active = False
    audit(db, user.id, "product.delete", "product", pid)
    db.commit()
    return {"ok": True}


@router.post("/products/import-csv")
async def import_csv(file: UploadFile = File(...), user: User = Depends(require("catalog.manage")), db: Session = Depends(get_db)):
    raw = (await file.read(2_000_000)).decode("utf-8-sig", errors="replace")
    created = updated = 0
    errors = []
    for n, row in enumerate(csv.DictReader(io.StringIO(raw)), start=2):
        try:
            body = ProductIn(sku=row["sku"], name=row["name"], category_slug=row["category_slug"],
                             product_type=row["product_type"], description=row.get("description", ""),
                             pack_size=row["pack_size"], unit_qty=float(row.get("unit_qty") or 1), unit=row.get("unit") or "kg",
                             price_paise=int(row["price_paise"]), cost_paise=int(row.get("cost_paise") or 0),
                             gst_rate_bp=int(row.get("gst_rate_bp") or 500), crops=row.get("crops", ""),
                             use_tags=row.get("use_tags", ""), safety_info=row.get("safety_info", ""))
            p = db.scalar(select(Product).where(Product.sku == body.sku))
            if p:
                _apply(p, body, db)
                updated += 1
            else:
                p = Product(is_demo=False)
                _apply(p, body, db)
                db.add(p)
                db.flush()
                db.add(InventoryBalance(product_id=p.id, location_id=co.platform_location(db).id, on_hand=0))
                created += 1
        except Exception as ex:  # report per-row problems without aborting
            errors.append({"row": n, "error": str(ex)[:150]})
    audit(db, user.id, "product.import_csv", detail={"created": created, "updated": updated, "errors": len(errors)})
    db.commit()
    return {"created": created, "updated": updated, "errors": errors}


# ---------- categories ----------
class CategoryIn(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9-]{2,60}$")
    name: str
    description: str = ""


@router.post("/categories", status_code=201)
def create_category(body: CategoryIn, user: User = Depends(require("catalog.manage")), db: Session = Depends(get_db)):
    c = ProductCategory(**body.model_dump())
    db.add(c)
    audit(db, user.id, "category.create", "category", body.slug)
    db.commit()
    return {"id": c.id}


# ---------- inventory ----------
class StockAdjust(BaseModel):
    product_id: int
    delta: int
    reason: str = Field(min_length=3, max_length=200)
    txn_type: InvTxnType = InvTxnType.ADJUSTMENT


@router.get("/inventory")
def inventory(user: User = Depends(require("inventory.manage")), db: Session = Depends(get_db)):
    rows = db.scalars(select(InventoryBalance)).unique().all()
    return [{"product_id": b.product_id, "sku": b.product.sku, "name": b.product.name, "on_hand": b.on_hand,
             "reserved": b.reserved, "reorder_threshold": b.reorder_threshold,
             "low": b.on_hand - b.reserved <= b.reorder_threshold} for b in rows]


@router.post("/inventory/adjust")
def adjust_stock(body: StockAdjust, user: User = Depends(require("inventory.manage")), db: Session = Depends(get_db)):
    if body.delta == 0:
        raise HTTPException(422, "delta must be non-zero")
    loc = co.platform_location(db)
    from sqlalchemy import update
    cond = [InventoryBalance.product_id == body.product_id, InventoryBalance.location_id == loc.id]
    if body.delta < 0:
        cond.append(InventoryBalance.on_hand - InventoryBalance.reserved >= -body.delta)  # never go negative
    res = db.execute(update(InventoryBalance).where(*cond).values(on_hand=InventoryBalance.on_hand + body.delta))
    if res.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "Adjustment would make stock negative, or product has no balance")
    db.add(InventoryTransaction(product_id=body.product_id, location_id=loc.id, txn_type=body.txn_type,
                                quantity_delta=body.delta, note=body.reason, actor_user_id=user.id, created_at=utcnow()))
    audit(db, user.id, "inventory.adjust", "product", body.product_id, {"delta": body.delta, "reason": body.reason})
    db.commit()
    return {"ok": True}


class Threshold(BaseModel):
    reorder_threshold: int = Field(ge=0, le=100000)


@router.put("/inventory/{product_id}/threshold")
def set_threshold(product_id: int, body: Threshold, user: User = Depends(require("inventory.manage")), db: Session = Depends(get_db)):
    b = db.scalar(select(InventoryBalance).where(InventoryBalance.product_id == product_id))
    if not b:
        raise HTTPException(404, "No inventory balance")
    b.reorder_threshold = body.reorder_threshold
    audit(db, user.id, "inventory.threshold", "product", product_id, {"value": body.reorder_threshold})
    db.commit()
    return {"ok": True}


# ---------- orders ----------
@router.get("/orders")
def admin_orders(status: OrderStatus | None = None, supplier_id: int | None = None, page: int = 1, size: int = 50,
                 user: User = Depends(require_any("orders.view_all", "district.manage")), db: Session = Depends(get_db)):
    stmt = select(Order).order_by(Order.id.desc())
    sc = district_scope(user)
    if sc:
        stmt = stmt.where(Order.district_id == sc)
    if status:
        stmt = stmt.where(Order.status == status)
    if supplier_id:
        stmt = stmt.where(Order.supplier_id == supplier_id)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    off, size = page_args(page, size)
    rows = db.scalars(stmt.offset(off).limit(size)).all()
    return {"total": total, "items": [order_out(o) | {"customer_id": o.user_id} for o in rows]}


class StatusIn(BaseModel):
    status: OrderStatus
    note: str | None = Field(default=None, max_length=200)


@router.post("/orders/{oid}/status")
def set_status(oid: int, body: StatusIn, user: User = Depends(require("orders.manage")), db: Session = Depends(get_db)):
    o = db.get(Order, oid)
    if not o:
        raise HTTPException(404, "Order not found")
    return order_out(co.set_status(db, o, body.status, user, body.note))


@router.get("/returns")
def returns(status: str = "REQUESTED", user: User = Depends(require("orders.manage")), db: Session = Depends(get_db)):
    from app.models import ReturnRequest
    rows = db.execute(select(ReturnRequest, Order.order_number).join(Order, Order.id == ReturnRequest.order_id)
                      .where(ReturnRequest.status == status).order_by(ReturnRequest.id).limit(100)).all()
    return [{"id": r.id, "order": n, "reason": r.reason, "status": r.status, "refund_paise": r.refund_paise} for r, n in rows]


class ReturnDecision(BaseModel):
    approve: bool
    note: str | None = Field(default=None, max_length=300)


@router.post("/returns/{rid}/decide")
def decide_return(rid: int, body: ReturnDecision, user: User = Depends(require("orders.manage")), db: Session = Depends(get_db)):
    from app.models import ReturnRequest
    from app.services.returns import decide_return as do
    r = db.get(ReturnRequest, rid)
    if not r:
        raise HTTPException(404, "Return not found")
    do(db, r, body.approve, user, body.note)
    return {"status": r.status}


# ---------- customers, promos ----------
@router.get("/customers")
def customers(q: str | None = None, page: int = 1, size: int = 50, user: User = Depends(require("customers.view")), db: Session = Depends(get_db)):
    stmt = select(User).join(Role).where(Role.name == RoleName.FARMER).order_by(User.id.desc())
    if q:
        stmt = stmt.where(func.lower(User.full_name).like(f"%{q.lower()}%") | User.phone.like(f"%{q}%"))
    off, size = page_args(page, size)
    farmers = db.scalars(stmt.offset(off).limit(size)).unique().all()
    ids = [u.id for u in farmers]
    stats = {uid: (c, t) for uid, c, t in db.execute(select(Order.user_id, func.count(Order.id), func.sum(Order.total_paise))
                                                      .where(Order.user_id.in_(ids), Order.status.not_in((OrderStatus.CANCELLED, OrderStatus.REJECTED)))
                                                      .group_by(Order.user_id))} if ids else {}
    return [{"id": u.id, "name": u.full_name, "mobile": u.phone, "email": u.email, "status": u.status.value, "is_demo": u.is_demo,
             "orders": stats.get(u.id, (0, 0))[0], "lifetime_value_paise": int(stats.get(u.id, (0, 0))[1] or 0)} for u in farmers]


class PromoIn(BaseModel):
    code: str = Field(pattern=r"^[A-Z0-9]{3,20}$")
    description: str = ""
    percent_off_bp: int = Field(ge=0, le=5000)
    max_discount_paise: int = Field(0, ge=0)
    min_order_paise: int = Field(0, ge=0)
    is_active: bool = True


@router.get("/promotions")
def promos(user: User = Depends(require("promotions.manage")), db: Session = Depends(get_db)):
    return [{c: getattr(p, c) for c in ("id", "code", "description", "percent_off_bp", "max_discount_paise",
                                        "min_order_paise", "is_active")} for p in db.scalars(select(Promotion))]


@router.post("/promotions", status_code=201)
def create_promo(body: PromoIn, user: User = Depends(require("promotions.manage")), db: Session = Depends(get_db)):
    if db.scalar(select(Promotion).where(Promotion.code == body.code)):
        raise HTTPException(409, "Code exists")
    p = Promotion(**body.model_dump())
    db.add(p)
    audit(db, user.id, "promotion.create", "promotion", body.code)
    db.commit()
    return {"id": p.id}


@router.get("/audit-logs")
def audit_logs(page: int = 1, size: int = 50, action: str | None = None,
               user: User = Depends(require("audit.view")), db: Session = Depends(get_db)):
    stmt = select(AuditLog).order_by(AuditLog.id.desc())
    if action:
        stmt = stmt.where(AuditLog.action.like(f"{action}%"))
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    off, size = page_args(page, size)
    return {"total": total, "items": [{"id": a.id, "actor": a.actor_user_id, "action": a.action, "entity": a.entity, "entity_id": a.entity_id,
                                       "detail": a.detail, "at": a.created_at.isoformat()} for a in db.scalars(stmt.offset(off).limit(size))]}


@router.get("/reports/orders.csv")
def orders_csv(range: str = "30d", start: str | None = None, end: str | None = None,
               user: User = Depends(require("reports.operational")), db: Session = Depends(get_db)):
    s, e = M.parse_range(range, start, end)
    rows = db.scalars(select(Order).where(Order.placed_at >= s, Order.placed_at < e).order_by(Order.id)).all()
    audit(db, user.id, "report.export", detail={"report": "orders"})
    db.commit()
    return csv_response("orders.csv", ["order_number", "placed_at", "status", "district", "subtotal_paise", "discount_paise",
                                       "delivery_fee_paise", "total_paise", "is_demo"],
                        [[o.order_number, o.placed_at.isoformat(), o.status.value, o.ship_district, o.subtotal_paise,
                          o.discount_paise, o.delivery_fee_paise, o.total_paise, o.is_demo] for o in rows])
