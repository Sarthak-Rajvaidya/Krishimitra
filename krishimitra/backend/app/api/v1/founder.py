from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.analytics import metrics as M
from app.api.deps import require, require_sensitive
from app.api.v1.csvutil import csv_response
from app.core.audit import audit
from app.db.session import get_db
from app.models import User

router = APIRouter(prefix="/founder", tags=["founder"])


def _growth(cur: int, prev: int):
    return round((cur - prev) * 100 / prev, 2) if prev > 0 else None  # None => unavailable, not invented


@router.get("/overview")
def overview(range: str = "30d", start: str | None = None, end: str | None = None,
             user: User = Depends(require("executive.view")), db: Session = Depends(get_db)):
    s, e = M.parse_range(range, start, end)
    span = e - s
    cur = M.finance_summary(db, s, e)
    prev = M.finance_summary(db, s - span, s)
    orders = M.order_summary(db, s, e)
    inv = M.inventory_overview(db, s, e)
    ai = M.ai_usage(db, s, e)
    alerts = []
    for l in inv["low_stock"][:5]:
        alerts.append({"level": "warn", "text": f"Low stock: {l['product']} ({l['available']} left)"})
    for r in inv["stockout_risk"][:5]:
        alerts.append({"level": "warn", "text": f"Stockout risk: {r['product']} ~{r['days_of_cover']} days of cover"})
    if ai["model_unavailable_count"]:
        alerts.append({"level": "info", "text": f"{ai['model_unavailable_count']} diagnoses ran while no trained model was active"})
    return {"range": {"start": s.isoformat(), "end": e.isoformat()}, "finance": cur,
            "net_sales_growth_pct": _growth(cur["net_sales_paise"], prev["net_sales_paise"]),
            "orders": orders, "category_sales": M.category_sales(db, s, e), "top_products": M.top_products(db, s, e, 5),
            "inventory": {"valuation_at_cost_paise": inv["valuation_at_cost_paise"], "slow_moving": inv["slow_moving"],
                          "stockout_risk": inv["stockout_risk"], "low_stock": inv["low_stock"]},
            "regions": M.region_revenue(db, s, e), "crop_issues": M.crop_issue_frequency(db, s, e), "ai": ai,
            "series": M.sales_series(db, s, e, "day"), "alerts": alerts,
            "data_notice": "Seeded demo records are flagged is_demo and mixed into totals in demo mode."}


@router.get("/export/summary.csv")
def export_summary(range: str = "30d", start: str | None = None, end: str | None = None,
                   user: User = Depends(require_sensitive("executive.sensitive", "founder.export_summary")),
                   db: Session = Depends(get_db)):
    s, e = M.parse_range(range, start, end)
    f = M.finance_summary(db, s, e)
    return csv_response("executive_summary.csv", ["metric", "value"],
                        [[k, v] for k, v in f.items() if not isinstance(v, (dict, str))])
