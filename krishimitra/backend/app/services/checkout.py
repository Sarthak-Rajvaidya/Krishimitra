"""Checkout and order lifecycle.

One cart can hold items from several suppliers. Checkout splits it into one Order per seller (all sharing `checkout_group`),
each reserving stock from that seller's own InventoryLocation. Stock is decremented with a conditional UPDATE so two buyers
can never take the last unit. Wallet payment debits all sub-orders in the same transaction, so it is all-or-nothing.
"""
import secrets
from collections import defaultdict
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.config import get_settings
from app.db.base import utcnow
from app.models import (Address, Cart, Delivery, FinancialTransaction, FinTxnType, InventoryBalance, InventoryLocation,
                        InventoryTransaction, InvTxnType, Order, OrderItem, OrderStatus, OrderStatusHistory, PaymentMode,
                        PaymentRecord, PaymentStatus, Promotion, Recommendation, RefundRecord, ServiceablePincode, User)
from app.services import wallet
from app.services.notify import notify
from app.services.pricing import Line, Totals, compute_totals, included_tax

CANCELLABLE = {OrderStatus.PLACED, OrderStatus.CONFIRMED, OrderStatus.PACKED}
# Supplier moves an order PLACED -> CONFIRMED -> PACKED -> READY_FOR_DISPATCH. Delivery partner/OTP moves the rest.
SUPPLIER_NEXT = {OrderStatus.PLACED: OrderStatus.CONFIRMED, OrderStatus.CONFIRMED: OrderStatus.PACKED,
                 OrderStatus.PACKED: OrderStatus.READY_FOR_DISPATCH}
PAID = (PaymentStatus.SIMULATED_PAID, PaymentStatus.COLLECTED)


def platform_location(db: Session) -> InventoryLocation:
    loc = db.scalar(select(InventoryLocation).where(InventoryLocation.supplier_id.is_(None), InventoryLocation.is_active.is_(True))
                    .order_by(InventoryLocation.id))
    if not loc:
        raise HTTPException(503, "No active warehouse configured")
    return loc


def supplier_location(db: Session, supplier_id: int) -> InventoryLocation:
    loc = db.scalar(select(InventoryLocation).where(InventoryLocation.supplier_id == supplier_id))
    if not loc:
        loc = InventoryLocation(code=f"S{supplier_id}", name=f"Supplier {supplier_id} stock", supplier_id=supplier_id)
        db.add(loc)
        db.flush()
    return loc


def serviceability(db: Session, pincode: str) -> ServiceablePincode:
    sp = db.scalar(select(ServiceablePincode).where(ServiceablePincode.pincode == pincode, ServiceablePincode.is_active.is_(True)).limit(1))
    if not sp:
        raise HTTPException(422, f"Delivery is not available to pincode {pincode} yet")
    return sp


def _lines(cart: Cart) -> list[Line]:
    out = []
    for it in cart.items:
        p = it.product
        if not p.is_active or p.deleted_at or p.approval_status != "APPROVED":
            raise HTTPException(409, f"'{p.name}' is no longer available")
        out.append(Line(p, it.quantity))
    return out


def price_cart(db: Session, cart: Cart, promo_code: str | None, delivery_fee: int) -> Totals:
    promo = db.scalar(select(Promotion).where(Promotion.code == promo_code.upper())) if promo_code else None
    return compute_totals(_lines(cart), promo, delivery_fee)


def _new_order_number() -> str:
    return f"KM-{utcnow():%Y%m%d}-{secrets.token_hex(3).upper()}"


def _history(order: Order, status: OrderStatus, actor: int | None, note: str | None, now: datetime) -> None:
    order.history.append(OrderStatusHistory(status=status, note=note, actor_user_id=actor, created_at=now))


def place_order(db: Session, user: User, address_id: int, payment_mode: PaymentMode, promo_code: str | None,
                idempotency_key: str | None, share_advisory: bool = False) -> list[Order]:
    if payment_mode not in (PaymentMode.COD, PaymentMode.WALLET):
        raise HTTPException(422, "Pay by wallet (top up first) or cash on delivery")
    if idempotency_key:
        prev = db.scalars(select(Order).where(Order.user_id == user.id, Order.idempotency_key.like(f"{idempotency_key}%"))).all()
        if prev:
            return list(prev)
    addr = db.get(Address, address_id)
    if not addr or addr.user_id != user.id:
        raise HTTPException(404, "Address not found")
    sp = serviceability(db, addr.pincode)
    cart = db.scalar(select(Cart).where(Cart.user_id == user.id))
    if not cart or not cart.items:
        raise HTTPException(400, "Cart is empty")

    promo = db.scalar(select(Promotion).where(Promotion.code == promo_code.upper())) if promo_code else None
    groups: dict[int | None, list[Line]] = defaultdict(list)
    for ln in _lines(cart):
        groups[ln.product.supplier_id].append(ln)
    now = utcnow()
    group_id = secrets.token_hex(8)
    rec_ids = [it.recommendation_id for it in cart.items if it.recommendation_id]
    recs = db.scalars(select(Recommendation).where(Recommendation.id.in_(rec_ids), Recommendation.user_id == user.id)).all() if rec_ids else []
    orders: list[Order] = []
    try:
        for n, (sup_id, lines) in enumerate(sorted(groups.items(), key=lambda kv: (kv[0] is None, kv[0] or 0))):
            loc = supplier_location(db, sup_id) if sup_id else platform_location(db)
            totals = compute_totals(lines, promo, sp.delivery_fee_paise if n == 0 else 0)   # one delivery fee per checkout
            for ln in sorted(totals.lines, key=lambda x: x.product.id):                      # fixed lock order avoids deadlocks
                res = db.execute(update(InventoryBalance).where(
                    InventoryBalance.product_id == ln.product.id, InventoryBalance.location_id == loc.id,
                    InventoryBalance.on_hand - InventoryBalance.reserved >= ln.qty).values(on_hand=InventoryBalance.on_hand - ln.qty))
                if res.rowcount != 1:
                    raise HTTPException(409, f"Insufficient stock for '{ln.product.name}'")
            o = Order(order_number=_new_order_number(), user_id=user.id, supplier_id=sup_id, checkout_group=group_id,
                      idempotency_key=f"{idempotency_key}:{n}" if idempotency_key else None, district_id=user.district_id,
                      status=OrderStatus.PLACED, payment_mode=payment_mode, subtotal_paise=totals.subtotal, discount_paise=totals.discount,
                      delivery_fee_paise=totals.delivery_fee, total_paise=totals.total, tax_paise=totals.tax, promo_code=totals.promo_code,
                      ship_name=user.full_name, ship_phone=user.phone, ship_line1=addr.line1, ship_district=addr.district,
                      ship_state=addr.state, ship_pincode=addr.pincode, location_id=loc.id, placed_at=now, is_demo=user.is_demo)
            for ln in totals.lines:
                o.items.append(OrderItem(product_id=ln.product.id, name_snapshot=ln.product.name, sku_snapshot=ln.product.sku,
                                         quantity=ln.qty, unit_price_paise=ln.product.price_paise, unit_cost_paise=ln.product.cost_paise,
                                         gst_rate_bp=ln.product.gst_rate_bp, line_total_paise=ln.line_total))
            _history(o, OrderStatus.PLACED, user.id, "Order placed", now)
            if share_advisory and recs:
                o.advisory_ref = {"recommendation_ids": [r.id for r in recs], "diagnosis_ids": sorted({r.diagnosis_id for r in recs if r.diagnosis_id})}
            db.add(o)
            db.flush()
            if payment_mode == PaymentMode.WALLET:
                wallet.debit(db, user.id, o.total_paise, "ORDER_PAYMENT", o.order_number)
            db.add(PaymentRecord(order_id=o.id, mode=payment_mode, status=PaymentStatus.PENDING if payment_mode == PaymentMode.COD else PaymentStatus.SIMULATED_PAID,
                                 amount_paise=o.total_paise, is_simulated=False))
            for ln in totals.lines:
                db.add(InventoryTransaction(product_id=ln.product.id, location_id=loc.id, txn_type=InvTxnType.SALE, quantity_delta=-ln.qty,
                                            reference=o.order_number, actor_user_id=user.id, created_at=now))
            if sup_id is None:
                _post_sale_ledger(db, o, totals, now)
            else:
                notify(db, sup_id, "ORDER", "New order received", f"{o.order_number} - Rs {o.total_paise / 100:.0f}", data={"order_id": o.id}, sms=True)
            orders.append(o)
        if share_advisory:
            for r in recs:
                r.order_id = orders[0].id
        for it in list(cart.items):
            db.delete(it)
        notify(db, user.id, "ORDER", "Order placed", ", ".join(o.order_number for o in orders), data={"order_ids": [o.id for o in orders]})
        audit(db, user.id, "order.place", "checkout", group_id, {"orders": len(orders), "total_paise": sum(o.total_paise for o in orders)})
        db.commit()
    except IntegrityError:
        db.rollback()
        if idempotency_key:
            prev = db.scalars(select(Order).where(Order.user_id == user.id, Order.idempotency_key.like(f"{idempotency_key}%"))).all()
            if prev:
                return list(prev)
        raise HTTPException(409, "Could not place order; please retry")
    except HTTPException:
        db.rollback()          # undo stock decrements and wallet debits made so far
        raise
    return orders


def _post_sale_ledger(db: Session, order: Order, totals: Totals, now: datetime) -> None:
    def add(t: FinTxnType, amt: int):
        if amt:
            db.add(FinancialTransaction(txn_type=t, amount_paise=amt, order_id=order.id, reference=order.order_number,
                                        is_demo=order.is_demo, occurred_at=now))
    add(FinTxnType.SALE, totals.subtotal - totals.tax_gross)
    add(FinTxnType.DISCOUNT, totals.discount - (totals.tax_gross - totals.tax))
    add(FinTxnType.GST_COLLECTED, totals.tax)
    add(FinTxnType.DELIVERY_FEE, totals.delivery_fee)
    add(FinTxnType.COGS, sum(l.product.cost_paise * l.qty for l in totals.lines))


def commission_of(order: Order) -> int:
    return (order.subtotal_paise - order.discount_paise) * get_settings().commission_bp // 10_000


def set_status(db: Session, order: Order, new: OrderStatus, actor: User, note: str | None = None) -> Order:
    """Supplier / admin progress an order up to READY_FOR_DISPATCH. Creates the delivery job at that point."""
    if new == OrderStatus.CANCELLED:
        return cancel_order(db, order, actor, note)
    if new == OrderStatus.REJECTED:
        if order.status != OrderStatus.PLACED:
            raise HTTPException(409, "Only a new order can be rejected")
        return cancel_order(db, order, actor, note or "Rejected by supplier", final=OrderStatus.REJECTED)
    if SUPPLIER_NEXT.get(order.status) != new:
        raise HTTPException(409, f"Cannot move order from {order.status.value} to {new.value}")
    now = utcnow()
    order.status = new
    _history(order, new, actor.id, note, now)
    if new == OrderStatus.READY_FOR_DISPATCH:
        if not db.scalar(select(Delivery.id).where(Delivery.order_id == order.id)):
            db.add(Delivery(order_id=order.id, fee_paise=get_settings().delivery_partner_fee_paise))
        notify_admins_for_dispatch(db, order)
    notify(db, order.user_id, "ORDER", f"Order {new.value.replace('_', ' ').lower()}", order.order_number, data={"order_id": order.id},
           dedupe_key=f"o{order.id}{new.value}")
    audit(db, actor.id, "order.status", "order", order.id, {"to": new.value})
    db.commit()
    return order


def notify_admins_for_dispatch(db: Session, order: Order) -> None:
    from app.services.notify import notify_role
    from app.models import RoleName
    notify_role(db, RoleName.ADMIN, "DELIVERY", "Order ready for dispatch", order.order_number, district_id=None)


def mark_delivered(db: Session, order: Order, actor_id: int | None) -> None:
    """Called after OTP verification. Collects COD, credits the supplier wallet net of commission, posts commission."""
    now = utcnow()
    order.status = OrderStatus.DELIVERED
    _history(order, OrderStatus.DELIVERED, actor_id, "Delivered (OTP verified)", now)
    for p in db.scalars(select(PaymentRecord).where(PaymentRecord.order_id == order.id)):
        if p.status == PaymentStatus.PENDING:
            p.status = PaymentStatus.COLLECTED
    if order.supplier_id:
        fee = commission_of(order)
        wallet.credit(db, order.supplier_id, order.subtotal_paise - order.discount_paise - fee, "SALE_EARNING", order.order_number)
        if fee:
            db.add(FinancialTransaction(txn_type=FinTxnType.COMMISSION, amount_paise=fee, order_id=order.id,
                                        reference=order.order_number, is_demo=order.is_demo, occurred_at=now))
        notify(db, order.supplier_id, "PAYOUT", "Order delivered - earnings credited", order.order_number)
    notify(db, order.user_id, "ORDER", "Order delivered", order.order_number, sms=True)


def cancel_order(db: Session, order: Order, actor: User, note: str | None = None, final: OrderStatus = OrderStatus.CANCELLED) -> Order:
    if order.status not in CANCELLABLE:
        raise HTTPException(409, f"Order in status {order.status.value} cannot be cancelled")
    now = utcnow()
    for it in order.items:
        db.execute(update(InventoryBalance).where(InventoryBalance.product_id == it.product_id, InventoryBalance.location_id == order.location_id)
                   .values(on_hand=InventoryBalance.on_hand + it.quantity))
        db.add(InventoryTransaction(product_id=it.product_id, location_id=order.location_id, txn_type=InvTxnType.CANCEL_RESTOCK,
                                    quantity_delta=it.quantity, reference=order.order_number, actor_user_id=actor.id, created_at=now))
    if order.supplier_id is None:
        tax_gross = sum(included_tax(i.line_total_paise, i.gst_rate_bp) for i in order.items)
        disc_tax = tax_gross - order.tax_paise
        for t, amt in ((FinTxnType.REFUND, (order.subtotal_paise - tax_gross) - (order.discount_paise - disc_tax)),
                       (FinTxnType.GST_REFUNDED, order.tax_paise), (FinTxnType.DELIVERY_FEE_REFUNDED, order.delivery_fee_paise),
                       (FinTxnType.COGS_REVERSAL, sum(i.unit_cost_paise * i.quantity for i in order.items))):
            if amt:
                db.add(FinancialTransaction(txn_type=t, amount_paise=amt, order_id=order.id, reference=order.order_number,
                                            is_demo=order.is_demo, occurred_at=now))
    if order.payment_mode == PaymentMode.WALLET:
        wallet.credit(db, order.user_id, order.total_paise, "REFUND", order.order_number)
        db.add(RefundRecord(order_id=order.id, amount_paise=order.total_paise, reason=note or "Order cancelled", actor_user_id=actor.id))
    order.status = final
    _history(order, final, actor.id, note, now)
    d = db.scalar(select(Delivery).where(Delivery.order_id == order.id))
    if d:
        from app.models import DeliveryStatus
        d.status = DeliveryStatus.FAILED
    notify(db, order.user_id, "ORDER", f"Order {final.value.lower()}", f"{order.order_number}. {note or ''}".strip())
    audit(db, actor.id, "order.cancel", "order", order.id)
    db.commit()
    return order

