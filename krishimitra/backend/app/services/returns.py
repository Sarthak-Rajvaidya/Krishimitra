from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.db.base import utcnow
from app.models import (FinancialTransaction, FinTxnType, InventoryBalance, InventoryTransaction, InvTxnType, Order, OrderStatus,
                        OrderStatusHistory, RefundRecord, ReturnRequest, User)
from app.services import checkout as co
from app.services import wallet
from app.services.notify import notify
from app.services.pricing import included_tax


def decide_return(db: Session, r: ReturnRequest, approve: bool, actor: User, note: str | None) -> ReturnRequest:
    """Approve = refund the item value (delivery fee is not refunded) to the farmer's wallet and restock."""
    if r.status != "REQUESTED":
        raise HTTPException(409, "Return already decided")
    o = db.get(Order, r.order_id)
    now = utcnow()
    r.decision_note = note
    if not approve:
        r.status = "REJECTED"
        o.status = OrderStatus.DELIVERED
        notify(db, r.user_id, "RETURN", "Return request declined", note or o.order_number)
        db.commit()
        return r
    refund = o.subtotal_paise - o.discount_paise
    r.status, r.refund_paise = "REFUNDED", refund
    o.status = OrderStatus.REFUNDED
    o.history.append(OrderStatusHistory(status=OrderStatus.REFUNDED, note=note or "Return approved", actor_user_id=actor.id, created_at=now))
    wallet.credit(db, r.user_id, refund, "REFUND", o.order_number)
    db.add(RefundRecord(order_id=o.id, amount_paise=refund, reason=r.reason, actor_user_id=actor.id))
    for it in o.items:
        db.execute(update(InventoryBalance).where(InventoryBalance.product_id == it.product_id, InventoryBalance.location_id == o.location_id)
                   .values(on_hand=InventoryBalance.on_hand + it.quantity))
        db.add(InventoryTransaction(product_id=it.product_id, location_id=o.location_id, txn_type=InvTxnType.RETURN,
                                    quantity_delta=it.quantity, reference=o.order_number, actor_user_id=actor.id, created_at=now))
    if o.supplier_id:
        # take back the supplier's earning (net of commission) as far as their balance allows; platform absorbs any shortfall
        fee = co.commission_of(o)
        wallet.debit(db, o.supplier_id, refund - fee, "RETURN_CLAWBACK", o.order_number, strict=False)
        if fee:
            db.add(FinancialTransaction(txn_type=FinTxnType.COMMISSION_REVERSAL, amount_paise=fee, order_id=o.id, reference=o.order_number,
                                        is_demo=o.is_demo, occurred_at=now))
    else:
        gross = sum(included_tax(i.line_total_paise, i.gst_rate_bp) for i in o.items)
        for t, amt in ((FinTxnType.REFUND, (o.subtotal_paise - gross) - (o.discount_paise - (gross - o.tax_paise))),
                       (FinTxnType.GST_REFUNDED, o.tax_paise), (FinTxnType.COGS_REVERSAL, sum(i.unit_cost_paise * i.quantity for i in o.items))):
            if amt:
                db.add(FinancialTransaction(txn_type=t, amount_paise=amt, order_id=o.id, reference=o.order_number, is_demo=o.is_demo, occurred_at=now))
    notify(db, r.user_id, "RETURN", "Refund credited to your wallet", f"Rs {refund / 100:.0f} - {o.order_number}", sms=True)
    audit(db, actor.id, "return.approve", "order", o.id, {"refund_paise": refund})
    db.commit()
    return r
