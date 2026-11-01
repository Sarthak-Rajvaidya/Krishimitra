"""Public marketplace browsing. Filtering, sorting and paging all happen in SQL so the catalogue can grow."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.v1.common import page_args, product_out, stock_map
from app.db.session import get_db
from app.models import (InventoryBalance, Product, ProductCategory, ProductType, ServiceablePincode, SupplierProfile, User, UserStatus)

router = APIRouter(tags=["catalog"])
LIVE = (Product.is_active.is_(True), Product.deleted_at.is_(None), Product.approval_status == "APPROVED")


@router.get("/categories")
def categories(db: Session = Depends(get_db)):
    rows = db.scalars(select(ProductCategory).where(ProductCategory.is_active.is_(True)).order_by(ProductCategory.id)).all()
    return [{"id": c.id, "slug": c.slug, "name": c.name, "description": c.description} for c in rows]


@router.get("/products")
def list_products(q: str | None = Query(None, max_length=80), category: str | None = None, product_type: ProductType | None = None,
                  crop: str | None = Query(None, max_length=60), brand: str | None = None, supplier_id: int | None = None,
                  min_price: int | None = Query(None, ge=0), max_price: int | None = Query(None, ge=0),
                  min_rating: float | None = Query(None, ge=0, le=5), in_stock: bool | None = None,
                  sort: str = "relevance", page: int = 1, size: int = 24, db: Session = Depends(get_db)):
    stmt = select(Product).where(*LIVE)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(Product.name).like(like), func.lower(Product.crops).like(like), func.lower(Product.use_tags).like(like),
                              func.lower(Product.brand).like(like)))
    if category:
        stmt = stmt.where(Product.category_id == select(ProductCategory.id).where(ProductCategory.slug == category).scalar_subquery())
    if product_type:
        stmt = stmt.where(Product.product_type == product_type)
    if crop:
        stmt = stmt.where(func.lower(Product.crops).like(f"%{crop.lower()}%"))
    if brand:
        stmt = stmt.where(func.lower(Product.brand) == brand.lower())
    if supplier_id:
        stmt = stmt.where(Product.supplier_id == supplier_id)
    if min_price is not None:
        stmt = stmt.where(Product.price_paise >= min_price)
    if max_price is not None:
        stmt = stmt.where(Product.price_paise <= max_price)
    if min_rating is not None:
        stmt = stmt.where(Product.rating_avg >= min_rating)
    if in_stock is not None:
        avail = select(InventoryBalance.product_id).where(InventoryBalance.on_hand - InventoryBalance.reserved > 0)
        stmt = stmt.where(Product.id.in_(avail) if in_stock else Product.id.not_in(avail))
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    order = {"price_asc": Product.price_paise.asc(), "price_desc": Product.price_paise.desc(),
             "rating": Product.rating_avg.desc(), "newest": Product.id.desc()}.get(sort, Product.name.asc())
    off, size = page_args(page, size)
    products = db.scalars(stmt.order_by(order, Product.id).offset(off).limit(size)).unique().all()
    stocks = stock_map(db, [p.id for p in products])
    return {"items": [product_out(p, stocks.get(p.id, 0)) for p in products], "total": total, "page": page, "size": size}


@router.get("/products/compare")
def compare(ids: str = Query(..., description="comma separated product ids, 2-4"), db: Session = Depends(get_db)):
    try:
        pids = [int(x) for x in ids.split(",") if x][:4]
    except ValueError:
        raise HTTPException(422, "ids must be numbers")
    if len(pids) < 2:
        raise HTTPException(422, "Pick at least two products to compare")
    ps = db.scalars(select(Product).where(Product.id.in_(pids), *LIVE)).unique().all()
    st = stock_map(db, [p.id for p in ps])
    return [{**product_out(p, st.get(p.id, 0)), "brand": p.brand, "specs": p.specs, "rating_avg": p.rating_avg, "rating_count": p.rating_count} for p in ps]


@router.get("/products/{pid}")
def get_product(pid: int, db: Session = Depends(get_db)):
    p = db.get(Product, pid)
    if not p or not p.is_active or p.deleted_at or p.approval_status != "APPROVED":
        raise HTTPException(404, "Product not found")
    sup = db.scalar(select(SupplierProfile).where(SupplierProfile.user_id == p.supplier_id)) if p.supplier_id else None
    return {**product_out(p, stock_map(db, [pid]).get(pid, 0)), "brand": p.brand, "specs": p.specs, "images": p.images,
            "rating_avg": p.rating_avg, "rating_count": p.rating_count, "supplier_id": p.supplier_id,
            "supplier_name": sup.shop_name if sup else "KrishiMitra"}


@router.get("/suppliers")
def suppliers(district: str | None = None, q: str | None = Query(None, max_length=60), page: int = 1, size: int = 20, db: Session = Depends(get_db)):
    """Approved suppliers. Used by 'nearby supplier' lookups, including those linked from AI recommendations."""
    stmt = select(SupplierProfile, User, UserStatus).join(User, User.id == SupplierProfile.user_id).where(User.status == UserStatus.ACTIVE, SupplierProfile.is_open.is_(True))
    if district:
        stmt = stmt.where(func.lower(SupplierProfile.district) == district.lower())
    if q:
        stmt = stmt.where(func.lower(SupplierProfile.shop_name).like(f"%{q.lower()}%"))
    off, size = page_args(page, size)
    rows = db.execute(stmt.order_by(SupplierProfile.rating_avg.desc(), SupplierProfile.id).offset(off).limit(size)).all()
    return [{"id": s.user_id, "shop_name": s.shop_name, "village": s.village, "district": s.district, "state": s.state,
             "latitude": s.latitude, "longitude": s.longitude, "categories": s.product_categories, "hours": s.operating_hours,
             "rating_avg": s.rating_avg, "rating_count": s.rating_count} for s, _ in rows]


@router.get("/serviceability/{pincode}")
def serviceability(pincode: str, db: Session = Depends(get_db)):
    sp = db.scalar(select(ServiceablePincode).where(ServiceablePincode.pincode == pincode, ServiceablePincode.is_active.is_(True)).limit(1))
    return {"pincode": pincode, "serviceable": bool(sp), "delivery_fee_paise": sp.delivery_fee_paise if sp else None}
