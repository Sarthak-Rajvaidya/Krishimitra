from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import InventoryBalance, Product


def stock_map(db: Session, ids: list[int] | None = None) -> dict[int, int]:
    q = select(InventoryBalance.product_id, func.sum(InventoryBalance.on_hand - InventoryBalance.reserved)).group_by(InventoryBalance.product_id)
    if ids is not None:
        q = q.where(InventoryBalance.product_id.in_(ids))
    return {pid: int(s or 0) for pid, s in db.execute(q)}


def product_out(p: Product, stock: int) -> dict:
    lab = p.label
    return {
        "id": p.id, "sku": p.sku, "name": p.name, "category": p.category.slug, "category_name": p.category.name,
        "product_type": p.product_type.value, "description": p.description, "pack_size": p.pack_size,
        "price_paise": p.price_paise, "unit_price_paise": round(p.price_paise / p.unit_qty) if p.unit_qty else None,
        "unit": p.unit, "image_url": p.image_url, "crops": [c for c in p.crops.split(",") if c],
        "use_tags": [c for c in p.use_tags.split(",") if c], "safety_info": p.safety_info,
        "in_stock": stock > 0, "stock": stock, "low_stock": 0 < stock <= 10,
        "is_demo": p.is_demo,
        "label_verified": bool(lab and lab.verified),
        "data_note": "Sample demo price/stock" if p.is_demo else None,
    }


def page_args(page: int, size: int) -> tuple[int, int]:
    size = max(1, min(size, 100))
    return (max(page, 1) - 1) * size, size
