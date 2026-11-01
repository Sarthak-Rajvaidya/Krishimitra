"""Farmer-facing cart, addresses, orders."""
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require
from app.api.v1.common import stock_map
from app.db.base import utcnow
from app.db.session import get_db
from app.models import (Address, Cart, CartItem, Delivery, DeliveryStatus, Order, OrderStatus, PaymentMode, Product, Recommendation,
                        ServiceablePincode, User)
from app.services import checkout as co

router = APIRouter(tags=["shop"])
farmer = require("shop.use")


def _cart(db: Session, user: User) -> Cart:
    c = db.scalar(select(Cart).where(Cart.user_id == user.id))
    if not c:
        c = Cart(user_id=user.id)
        db.add(c)
        db.commit()
    return c


def cart_out(db: Session, user: User, cart: Cart, promo: str | None = None, pincode: str | None = None) -> dict:
    fee = 0
    if pincode:
        sp = db.scalar(select(ServiceablePincode).where(ServiceablePincode.pincode == pincode, ServiceablePincode.is_active.is_(True)).limit(1))
        fee = sp.delivery_fee_paise if sp else 0
    stocks = stock_map(db, [i.product_id for i in cart.items])
    items = [{"id": i.id, "product_id": i.product_id, "name": i.product.name, "pack_size": i.product.pack_size,
              "unit_price_paise": i.product.price_paise, "quantity": i.quantity,
              "line_total_paise": i.product.price_paise * i.quantity, "available": stocks.get(i.product_id, 0),
              "recommendation_id": i.recommendation_id} for i in cart.items]
    if not cart.items:
        return {"items": [], "subtotal_paise": 0, "discount_paise": 0, "delivery_fee_paise": 0, "total_paise": 0}
    try:
        t = co.price_cart(db, cart, promo, fee)
    except HTTPException:
        raise
    return {"items": items, "subtotal_paise": t.subtotal, "discount_paise": t.discount,
            "delivery_fee_paise": t.delivery_fee, "total_paise": t.total, "tax_included_paise": t.tax,
            "promo_code": t.promo_code, "delivery_fee_applies": bool(pincode)}


class CartAdd(BaseModel):
    product_id: int
    quantity: int = Field(1, ge=1, le=100)
    recommendation_id: int | None = None


class CartQty(BaseModel):
    quantity: int = Field(ge=1, le=100)


@router.get("/cart")
def get_cart(promo: str | None = None, pincode: str | None = None, user: User = Depends(farmer), db: Session = Depends(get_db)):
    return cart_out(db, user, _cart(db, user), promo, pincode)


@router.post("/cart/items")
def add_item(body: CartAdd, user: User = Depends(farmer), db: Session = Depends(get_db)):
    p = db.get(Product, body.product_id)
    if not p or not p.is_active or p.deleted_at:
        raise HTTPException(404, "Product not found")
    cart = _cart(db, user)
    rec = None
    if body.recommendation_id:
        rec = db.get(Recommendation, body.recommendation_id)
        if not rec or rec.user_id != user.id:
            raise HTTPException(404, "Recommendation not found")
    item = next((i for i in cart.items if i.product_id == p.id), None)
    if item:
        item.quantity = min(item.quantity + body.quantity, 100)
    else:
        item = CartItem(cart_id=cart.id, product_id=p.id, quantity=body.quantity,
                        recommendation_id=body.recommendation_id)
        db.add(item)
    if rec:
        rec.added_to_cart_at = utcnow()
    db.commit()
    db.refresh(cart)
    return cart_out(db, user, cart)


@router.put("/cart/items/{item_id}")
def set_qty(item_id: int, body: CartQty, user: User = Depends(farmer), db: Session = Depends(get_db)):
    cart = _cart(db, user)
    it = next((i for i in cart.items if i.id == item_id), None)
    if not it:
        raise HTTPException(404, "Item not in cart")
    it.quantity = body.quantity
    db.commit()
    db.refresh(cart)
    return cart_out(db, user, cart)


@router.delete("/cart/items/{item_id}")
def remove_item(item_id: int, user: User = Depends(farmer), db: Session = Depends(get_db)):
    cart = _cart(db, user)
    it = next((i for i in cart.items if i.id == item_id), None)
    if not it:
        raise HTTPException(404, "Item not in cart")
    db.delete(it)
    db.commit()
    db.refresh(cart)
    return cart_out(db, user, cart)


# ---- addresses ----
class AddressIn(BaseModel):
    label: str = "Home"
    line1: str = Field(min_length=3, max_length=255)
    village: str | None = None
    district: str
    state: str
    pincode: str = Field(pattern=r"^\d{6}$")
    is_default: bool = False


def addr_out(a: Address) -> dict:
    return {c: getattr(a, c) for c in ("id", "label", "line1", "village", "district", "state", "pincode", "is_default")}


@router.get("/addresses")
def list_addresses(user: User = Depends(farmer), db: Session = Depends(get_db)):
    return [addr_out(a) for a in db.scalars(select(Address).where(Address.user_id == user.id))]


@router.post("/addresses", status_code=201)
def add_address(body: AddressIn, user: User = Depends(farmer), db: Session = Depends(get_db)):
    a = Address(user_id=user.id, **body.model_dump())
    db.add(a)
    db.commit()
    return addr_out(a)


@router.delete("/addresses/{aid}")
def del_address(aid: int, user: User = Depends(farmer), db: Session = Depends(get_db)):
    a = db.get(Address, aid)
    if not a or a.user_id != user.id:
        raise HTTPException(404, "Address not found")
    db.delete(a)
    db.commit()
    return {"ok": True}


# ---- orders ----
class CheckoutIn(BaseModel):
    address_id: int
    payment_mode: PaymentMode
    promo_code: str | None = None
    share_advisory: bool = False


def order_out(o: Order, delivery: Delivery | None = None) -> dict:
    d = {"id": o.id, "order_number": o.order_number, "checkout_group": o.checkout_group, "supplier_id": o.supplier_id,
         "status": o.status.value, "payment_mode": o.payment_mode.value,
         "subtotal_paise": o.subtotal_paise, "discount_paise": o.discount_paise,
         "delivery_fee_paise": o.delivery_fee_paise, "total_paise": o.total_paise, "tax_included_paise": o.tax_paise,
         "placed_at": o.placed_at.isoformat(), "is_demo": o.is_demo,
         "ship_to": {"name": o.ship_name, "line1": o.ship_line1, "district": o.ship_district,
                     "state": o.ship_state, "pincode": o.ship_pincode},
         "items": [{"product_id": i.product_id, "name": i.name_snapshot, "sku": i.sku_snapshot,
                    "quantity": i.quantity, "unit_price_paise": i.unit_price_paise,
                    "line_total_paise": i.line_total_paise} for i in o.items],
         "timeline": [{"status": h.status.value, "note": h.note, "at": h.created_at.isoformat()} for h in o.history]}
    if delivery:
        d["delivery"] = {"status": delivery.status.value, "due_by": delivery.due_by.isoformat() if delivery.due_by else None,
                         # the farmer reads this code to the delivery partner at the door
                         "otp": delivery.otp_plain_for_farmer if delivery.status in (DeliveryStatus.ACCEPTED, DeliveryStatus.PICKED_UP) else None}
    return d


@router.post("/checkout", status_code=201)
def checkout(body: CheckoutIn, user: User = Depends(farmer), db: Session = Depends(get_db),
             idempotency_key: str | None = Header(default=None, max_length=64)):
    """Splits the cart per supplier. Returns one order per seller."""
    orders = co.place_order(db, user, body.address_id, body.payment_mode, body.promo_code, idempotency_key, body.share_advisory)
    return {"orders": [order_out(o) for o in orders], "total_paise": sum(o.total_paise for o in orders)}


@router.get("/orders")
def my_orders(page: int = 1, size: int = 20, user: User = Depends(farmer), db: Session = Depends(get_db)):
    size = max(1, min(size, 50))
    rows = db.scalars(select(Order).where(Order.user_id == user.id).order_by(Order.id.desc()).offset((max(page, 1) - 1) * size).limit(size)).all()
    dl = {d.order_id: d for d in db.scalars(select(Delivery).where(Delivery.order_id.in_([o.id for o in rows])))} if rows else {}
    return [order_out(o, dl.get(o.id)) for o in rows]


@router.get("/orders/{oid}")
def my_order(oid: int, user: User = Depends(farmer), db: Session = Depends(get_db)):
    o = db.get(Order, oid)
    if not o or o.user_id != user.id:  # isolation: other farmers' orders look nonexistent
        raise HTTPException(404, "Order not found")
    return order_out(o, db.scalar(select(Delivery).where(Delivery.order_id == o.id)))


@router.post("/orders/{oid}/cancel")
def cancel_my_order(oid: int, user: User = Depends(farmer), db: Session = Depends(get_db)):
    o = db.get(Order, oid)
    if not o or o.user_id != user.id:
        raise HTTPException(404, "Order not found")
    if o.status not in (OrderStatus.PLACED, OrderStatus.CONFIRMED):
        raise HTTPException(409, "Order can no longer be cancelled")
    return order_out(co.cancel_order(db, o, user, "Cancelled by customer"))
