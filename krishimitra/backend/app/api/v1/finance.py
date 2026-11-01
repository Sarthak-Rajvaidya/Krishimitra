from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics import metrics as M
from app.api.deps import require
from app.api.v1.common import page_args
from app.api.v1.csvutil import csv_response
from app.core.audit import audit
from app.db.base import utcnow
from app.db.session import get_db
from app.models import Expense, FinancialTransaction, Order, PaymentRecord, PaymentStatus, RefundRecord, User

router = APIRouter(prefix="/finance", tags=["finance"])
view = require("finance.view")


@router.get("/overview")
def overview(range: str = "30d", start: str | None = None, end: str | None = None,
             user: User = Depends(view), db: Session = Depends(get_db)):
    s, e = M.parse_range(range, start, end)
    return {"range": {"start": s.isoformat(), "end": e.isoformat()}, "summary": M.finance_summary(db, s, e),
            "series": M.sales_series(db, s, e, "day"),
            "definitions": {"net_sales": "SALE - DISCOUNT - REFUND (ex-GST)", "gross_margin": "(net_sales - COGS) / net_sales",
                            "gst": "GST contained in GST-inclusive prices, rounded half-up per line. Estimate only; not a tax filing."}}


@router.get("/ledger")
def ledger(range: str = "30d", start: str | None = None, end: str | None = None, page: int = 1, size: int = 100,
           user: User = Depends(view), db: Session = Depends(get_db)):
    s, e = M.parse_range(range, start, end)
    rows = db.scalars(select(FinancialTransaction).where(FinancialTransaction.occurred_at >= s, FinancialTransaction.occurred_at < e)
                      .order_by(FinancialTransaction.id.desc())).all()
    off, size = page_args(page, size)
    return {"total": len(rows), "items": [{"id": t.id, "type": t.txn_type.value, "amount_paise": t.amount_paise,
                                           "reference": t.reference, "is_demo": t.is_demo, "at": t.occurred_at.isoformat()}
                                          for t in rows[off:off + size]]}


@router.get("/reconciliation")
def reconciliation(user: User = Depends(view), db: Session = Depends(get_db)):
    rows = db.execute(select(PaymentRecord.mode, PaymentRecord.status, func.count(PaymentRecord.id),
                             func.sum(PaymentRecord.amount_paise)).group_by(PaymentRecord.mode, PaymentRecord.status)).all()
    return {"note": "All payments in this prototype are COD or simulated. No gateway settlement data exists.",
            "rows": [{"mode": m.value, "status": s.value, "count": int(c), "amount_paise": int(a or 0)} for m, s, c, a in rows]}


@router.get("/expenses")
def expenses(user: User = Depends(view), db: Session = Depends(get_db)):
    return [{"id": x.id, "category": x.category, "description": x.description, "amount_paise": x.amount_paise,
             "incurred_on": x.incurred_on.isoformat(), "is_demo": x.is_demo}
            for x in db.scalars(select(Expense).order_by(Expense.incurred_on.desc()).limit(200))]


class ExpenseIn(BaseModel):
    category: str = Field(min_length=2, max_length=60)
    description: str = Field("", max_length=255)
    amount_paise: int = Field(gt=0)


@router.post("/expenses", status_code=201)
def add_expense(body: ExpenseIn, user: User = Depends(require("finance.write")), db: Session = Depends(get_db)):
    now = utcnow()
    x = Expense(**body.model_dump(), incurred_on=now, recorded_by=user.id)
    db.add(x)
    audit(db, user.id, "expense.create", "expense", detail=body.model_dump())
    db.commit()
    return {"id": x.id}


@router.get("/gst")
def gst(range: str = "30d", start: str | None = None, end: str | None = None,
        user: User = Depends(view), db: Session = Depends(get_db)):
    s, e = M.parse_range(range, start, end)
    f = M.finance_summary(db, s, e)
    return {"gst_collected_paise": f["gst_collected_paise"], "gst_refunded_paise": f["gst_refunded_paise"],
            "gst_net_paise": f["gst_net_paise"],
            "disclaimer": "Operational estimate derived from the ledger. Not a GST return and not a compliance certification."}


@router.get("/refunds")
def refunds(user: User = Depends(view), db: Session = Depends(get_db)):
    return [{"id": r.id, "order_id": r.order_id, "amount_paise": r.amount_paise, "reason": r.reason, "at": r.created_at.isoformat()}
            for r in db.scalars(select(RefundRecord).order_by(RefundRecord.id.desc()).limit(200))]


@router.get("/export/ledger.csv")
def export_ledger(range: str = "30d", start: str | None = None, end: str | None = None,
                  user: User = Depends(view), db: Session = Depends(get_db)):
    s, e = M.parse_range(range, start, end)
    rows = db.scalars(select(FinancialTransaction).where(FinancialTransaction.occurred_at >= s, FinancialTransaction.occurred_at < e)
                      .order_by(FinancialTransaction.id)).all()
    audit(db, user.id, "finance.export", detail={"report": "ledger"})
    db.commit()
    return csv_response("ledger.csv", ["id", "type", "amount_paise", "reference", "is_demo", "occurred_at"],
                        [[t.id, t.txn_type.value, t.amount_paise, t.reference, t.is_demo, t.occurred_at.isoformat()] for t in rows])
