"""Dashboard aggregates. All money in integer paise.

METRIC DEFINITIONS (also in README):
- gross_order_value  = sum(orders.total_paise) for non-cancelled orders placed in range (incl. GST + delivery).
- net_sales          = SALE - DISCOUNT - REFUND ledger entries (ex-GST item revenue, after discounts and reversals).
- cogs               = COGS - COGS_REVERSAL (unit cost snapshot at order time).
- gross_profit       = net_sales - cogs.      gross_margin_pct = gross_profit / net_sales.
- operating_profit   = gross_profit - recorded expenses (only expenses present in the expenses table).
- gst_net            = GST_COLLECTED - GST_REFUNDED (a liability estimate, NOT a tax filing).
- repeat_customer    = customer with >= 2 non-cancelled orders in the range.
Revenue is recognised at order placement and reversed on cancellation (demo simplification).
"""
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import (AdvisoryConversation, AdvisoryMessage, CropDiagnosis, DiagnosisStatus, Expense,
                        FinancialTransaction, FinTxnType as F, InventoryBalance, LLMCallLog, Order, OrderItem,
                        OrderStatus, Product, ProductCategory, RefundRecord, PaymentRecord, User)


def parse_range(rng: str = "30d", start: str | None = None, end: str | None = None) -> tuple[datetime, datetime]:
    now = utcnow()
    if rng == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0), now
    if rng in ("7d", "30d", "90d"):
        return now - timedelta(days=int(rng[:-1])), now
    if rng == "custom":
        try:
            s = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
            e = datetime.fromisoformat(end).replace(tzinfo=timezone.utc) + timedelta(days=1)
        except Exception:
            raise HTTPException(422, "Custom range needs valid ISO start and end dates")
        if e <= s:
            raise HTTPException(422, "end must be after start")
        return s, e
    raise HTTPException(422, "range must be today|7d|30d|90d|custom")


def _ledger(db: Session, s, e, demo: bool | None) -> dict[str, int]:
    q = select(FinancialTransaction.txn_type, func.coalesce(func.sum(FinancialTransaction.amount_paise), 0)) \
        .where(FinancialTransaction.occurred_at >= s, FinancialTransaction.occurred_at < e)
    if demo is not None:
        q = q.where(FinancialTransaction.is_demo == demo)
    return {t.value: int(v) for t, v in db.execute(q.group_by(FinancialTransaction.txn_type))}


def finance_summary(db: Session, s, e, demo: bool | None = None) -> dict:
    L = lambda k: _ledger_cache.get(k, 0)  # noqa: E731
    _ledger_cache = _ledger(db, s, e, demo)
    net_sales = L("SALE") - L("DISCOUNT") - L("REFUND")
    cogs = L("COGS") - L("COGS_REVERSAL")
    gp = net_sales - cogs
    eq = select(func.coalesce(func.sum(Expense.amount_paise), 0)).where(Expense.incurred_on >= s, Expense.incurred_on < e)
    if demo is not None:
        eq = eq.where(Expense.is_demo == demo)
    expenses = int(db.scalar(eq))
    cats = db.execute(select(Expense.category, func.sum(Expense.amount_paise)).where(
        Expense.incurred_on >= s, Expense.incurred_on < e).group_by(Expense.category)).all()
    return {
        "gross_sales_paise": L("SALE"), "discounts_paise": L("DISCOUNT"), "refunds_paise": L("REFUND"),
        "net_sales_paise": net_sales, "delivery_fees_paise": L("DELIVERY_FEE") - L("DELIVERY_FEE_REFUNDED"),
        "cogs_paise": cogs, "gross_profit_paise": gp,
        "gross_margin_pct": round(gp * 100 / net_sales, 2) if net_sales > 0 else None,
        "expenses_paise": expenses, "expense_categories_included": {c: int(v) for c, v in cats},
        "operating_profit_paise": gp - expenses,
        "gst_collected_paise": L("GST_COLLECTED"), "gst_refunded_paise": L("GST_REFUNDED"),
        "gst_net_paise": L("GST_COLLECTED") - L("GST_REFUNDED"),
        "profit_note": "Operating profit includes only expenses recorded in the system; unrecorded costs are not estimated.",
    }


def order_summary(db: Session, s, e) -> dict:
    base = (Order.placed_at >= s, Order.placed_at < e)
    live = Order.status != OrderStatus.CANCELLED
    n, gov = db.execute(select(func.count(Order.id), func.coalesce(func.sum(Order.total_paise), 0)).where(*base, live)).one()
    total_all = db.scalar(select(func.count(Order.id)).where(*base))
    cancelled = db.scalar(select(func.count(Order.id)).where(*base, Order.status == OrderStatus.CANCELLED))
    by_status = {st.value: c for st, c in db.execute(select(Order.status, func.count(Order.id)).where(*base).group_by(Order.status))}
    refunds = int(db.scalar(select(func.coalesce(func.sum(RefundRecord.amount_paise), 0)).where(
        RefundRecord.created_at >= s, RefundRecord.created_at < e)))
    per_cust = db.execute(select(Order.user_id, func.count(Order.id)).where(*base, live).group_by(Order.user_id)).all()
    customers = len(per_cust)
    repeat = sum(1 for _, c in per_cust if c >= 2)
    first_seen = dict(db.execute(select(Order.user_id, func.min(Order.placed_at)).group_by(Order.user_id)).all())
    new_customers = sum(1 for uid, _ in per_cust if s <= _naive(first_seen[uid], s) < e)
    return {"orders": int(n), "gross_order_value_paise": int(gov), "aov_paise": int(gov // n) if n else None,
            "pending_orders": sum(by_status.get(k, 0) for k in ("PLACED", "CONFIRMED", "PACKED", "OUT_FOR_DELIVERY")),
            "delivered_orders": by_status.get("DELIVERED", 0), "status_distribution": by_status,
            "cancellation_rate_pct": round(cancelled * 100 / total_all, 2) if total_all else None,
            "refund_total_paise": refunds, "customers": customers, "repeat_customers": repeat,
            "new_customers": new_customers,
            "repeat_purchase_rate_pct": round(repeat * 100 / customers, 2) if customers else None}


def _naive(dt: datetime, ref: datetime) -> datetime:
    return dt.replace(tzinfo=ref.tzinfo) if dt.tzinfo is None else dt


def sales_series(db: Session, s, e, bucket: str = "day") -> list[dict]:
    day = func.date(FinancialTransaction.occurred_at) if bucket == "day" else func.strftime("%Y-%m", FinancialTransaction.occurred_at) \
        if db.bind.dialect.name == "sqlite" else func.to_char(FinancialTransaction.occurred_at, "YYYY-MM")
    sign = case((FinancialTransaction.txn_type == F.SALE, FinancialTransaction.amount_paise),
                (FinancialTransaction.txn_type.in_([F.DISCOUNT, F.REFUND]), -FinancialTransaction.amount_paise), else_=0)
    cogs = case((FinancialTransaction.txn_type == F.COGS, FinancialTransaction.amount_paise),
                (FinancialTransaction.txn_type == F.COGS_REVERSAL, -FinancialTransaction.amount_paise), else_=0)
    rows = db.execute(select(day, func.sum(sign), func.sum(cogs)).where(
        FinancialTransaction.occurred_at >= s, FinancialTransaction.occurred_at < e).group_by(day).order_by(day)).all()
    return [{"period": str(d), "net_sales_paise": int(n or 0), "gross_profit_paise": int((n or 0) - (c or 0))} for d, n, c in rows]


def category_sales(db: Session, s, e) -> list[dict]:
    rows = db.execute(select(ProductCategory.name, func.sum(OrderItem.line_total_paise), func.sum(OrderItem.quantity))
                      .join(Product, Product.id == OrderItem.product_id).join(ProductCategory, ProductCategory.id == Product.category_id)
                      .join(Order, Order.id == OrderItem.order_id)
                      .where(Order.placed_at >= s, Order.placed_at < e, Order.status != OrderStatus.CANCELLED)
                      .group_by(ProductCategory.name).order_by(func.sum(OrderItem.line_total_paise).desc())).all()
    return [{"category": n, "sales_paise": int(v), "units": int(q)} for n, v, q in rows]


def top_products(db: Session, s, e, limit: int = 10) -> list[dict]:
    rows = db.execute(select(OrderItem.name_snapshot, func.sum(OrderItem.quantity), func.sum(OrderItem.line_total_paise))
                      .join(Order, Order.id == OrderItem.order_id)
                      .where(Order.placed_at >= s, Order.placed_at < e, Order.status != OrderStatus.CANCELLED)
                      .group_by(OrderItem.name_snapshot).order_by(func.sum(OrderItem.quantity).desc()).limit(limit)).all()
    return [{"product": n, "units": int(q), "sales_paise": int(v)} for n, q, v in rows]


def inventory_overview(db: Session, s, e) -> dict:
    rows = db.scalars(select(InventoryBalance)).unique().all()
    levels, low, valuation = [], [], 0
    sold = dict(db.execute(select(OrderItem.product_id, func.sum(OrderItem.quantity)).join(Order, Order.id == OrderItem.order_id)
                           .where(Order.placed_at >= s, Order.placed_at < e, Order.status != OrderStatus.CANCELLED)
                           .group_by(OrderItem.product_id)).all())
    slow, stockout_risk = [], []
    days = max((e - s).days, 1)
    for b in rows:
        avail = b.on_hand - b.reserved
        levels.append({"product": b.product.name, "sku": b.product.sku, "on_hand": b.on_hand, "available": avail,
                       "threshold": b.reorder_threshold})
        valuation += b.on_hand * b.product.cost_paise
        if avail <= b.reorder_threshold:
            low.append({"product": b.product.name, "available": avail, "threshold": b.reorder_threshold})
        if b.on_hand > 0 and sold.get(b.product_id, 0) == 0:
            slow.append({"product": b.product.name, "on_hand": b.on_hand})
        rate = sold.get(b.product_id, 0) / days
        if rate > 0 and avail / rate < 7:
            stockout_risk.append({"product": b.product.name, "days_of_cover": round(avail / rate, 1)})
    return {"levels": levels, "low_stock": low, "valuation_at_cost_paise": valuation,
            "slow_moving": slow, "stockout_risk": stockout_risk, "slow_moving_definition": "In stock with zero sales in the selected range"}


def region_revenue(db: Session, s, e) -> list[dict]:
    rows = db.execute(select(Order.ship_district, func.sum(Order.total_paise), func.count(Order.id)).where(
        Order.placed_at >= s, Order.placed_at < e, Order.status != OrderStatus.CANCELLED).group_by(Order.ship_district)).all()
    return [{"district": d, "revenue_paise": int(v), "orders": int(c)} for d, v, c in rows]


def ai_usage(db: Session, s, e) -> dict:
    diag = db.execute(select(CropDiagnosis.status, func.count(CropDiagnosis.id)).where(
        CropDiagnosis.created_at >= s, CropDiagnosis.created_at < e).group_by(CropDiagnosis.status)).all()
    d = {st.value: c for st, c in diag}
    total = sum(d.values())
    convs = db.scalar(select(func.count(AdvisoryConversation.id)).where(AdvisoryConversation.created_at >= s, AdvisoryConversation.created_at < e))
    msgs = db.scalar(select(func.count(AdvisoryMessage.id)).where(AdvisoryMessage.created_at >= s, AdvisoryMessage.created_at < e,
                                                                   AdvisoryMessage.role == "assistant"))
    ungrounded = db.scalar(select(func.count(AdvisoryMessage.id)).where(
        AdvisoryMessage.created_at >= s, AdvisoryMessage.created_at < e, AdvisoryMessage.grounded == False))  # noqa: E712
    prov = db.execute(select(LLMCallLog.provider, func.count(LLMCallLog.id), func.sum(case((LLMCallLog.ok, 1), else_=0)),
                             func.avg(LLMCallLog.latency_ms)).where(LLMCallLog.created_at >= s, LLMCallLog.created_at < e)
                      .group_by(LLMCallLog.provider)).all()
    return {"diagnoses": total, "diagnoses_by_status": d,
            "low_confidence_rate_pct": round(d.get("LOW_CONFIDENCE", 0) * 100 / total, 2) if total else None,
            "model_unavailable_count": d.get("MODEL_UNAVAILABLE", 0),
            "advisory_conversations": int(convs), "advisory_answers": int(msgs), "ungrounded_answers": int(ungrounded),
            "llm_providers": [{"provider": p, "calls": int(c), "success": int(ok or 0), "avg_latency_ms": round(float(a or 0))}
                              for p, c, ok, a in prov]}


def crop_issue_frequency(db: Session, s, e) -> list[dict]:
    from app.models import DiagnosisPrediction
    rows = db.execute(select(DiagnosisPrediction.class_label, func.count(DiagnosisPrediction.id))
                      .join(CropDiagnosis, CropDiagnosis.id == DiagnosisPrediction.diagnosis_id)
                      .where(DiagnosisPrediction.rank == 1, CropDiagnosis.created_at >= s, CropDiagnosis.created_at < e)
                      .group_by(DiagnosisPrediction.class_label).order_by(func.count(DiagnosisPrediction.id).desc()).limit(10)).all()
    return [{"label": l, "count": int(c)} for l, c in rows]
