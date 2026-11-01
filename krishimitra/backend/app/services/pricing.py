"""Server-side money math. All amounts are integer paise. Product prices are GST-inclusive."""
from dataclasses import dataclass, field
from datetime import datetime

from app.db.base import utcnow
from app.models import Product, Promotion

FREE_DELIVERY_ABOVE_PAISE = 50_000  # demo rule: free delivery above Rs 500


@dataclass
class Line:
    product: Product
    qty: int
    line_total: int = 0


@dataclass
class Totals:
    subtotal: int
    discount: int
    delivery_fee: int
    total: int
    tax: int
    tax_gross: int
    promo_code: str | None = None
    lines: list[Line] = field(default_factory=list)


def included_tax(amount_paise: int, rate_bp: int) -> int:
    """GST contained in a GST-inclusive amount, rounded half-up."""
    return (amount_paise * rate_bp + (10_000 + rate_bp) // 2) // (10_000 + rate_bp)


def promo_discount(promo: Promotion | None, subtotal: int, now: datetime | None = None) -> int:
    if not promo or not promo.is_active:
        return 0
    now = now or utcnow()
    if promo.starts_at and promo.starts_at.replace(tzinfo=now.tzinfo) > now:
        return 0
    if promo.ends_at and promo.ends_at.replace(tzinfo=now.tzinfo) < now:
        return 0
    if subtotal < promo.min_order_paise:
        return 0
    d = subtotal * promo.percent_off_bp // 10_000
    if promo.max_discount_paise:
        d = min(d, promo.max_discount_paise)
    return min(d, subtotal)


def compute_totals(lines: list[Line], promo: Promotion | None, base_delivery_fee: int) -> Totals:
    subtotal = 0
    tax_gross = 0
    for ln in lines:
        ln.line_total = ln.product.price_paise * ln.qty
        subtotal += ln.line_total
        tax_gross += included_tax(ln.line_total, ln.product.gst_rate_bp)
    discount = promo_discount(promo, subtotal)
    tax = tax_gross if subtotal == 0 else tax_gross * (subtotal - discount) // subtotal
    after = subtotal - discount
    fee = 0 if after >= FREE_DELIVERY_ABOVE_PAISE or after == 0 else base_delivery_fee
    return Totals(subtotal, discount, fee, after + fee, tax, tax_gross,
                  promo.code if discount else None, lines)
