"""Payment gateway adapter used for wallet top-ups.

`razorpay`  : real orders via Razorpay REST API; success only after the server verifies the checkout signature.
`simulated` : development only. No money moves. Disabled when APP_ENV=production.
"""
import hashlib
import hmac
import secrets

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import GatewayOrder
from app.services import wallet


def create_topup(db: Session, user_id: int, amount_paise: int) -> dict:
    s = get_settings()
    if s.payment_provider == "razorpay":
        if not (s.razorpay_key_id and s.razorpay_key_secret):
            raise HTTPException(503, "Online payments are not configured")
        try:
            r = httpx.post("https://api.razorpay.com/v1/orders", auth=(s.razorpay_key_id, s.razorpay_key_secret), timeout=10,
                           json={"amount": amount_paise, "currency": "INR", "receipt": f"w{user_id}-{secrets.token_hex(4)}"})
            r.raise_for_status()
        except httpx.HTTPError:
            raise HTTPException(502, "Payment provider did not respond. Please try again")
        oid, simulated = r.json()["id"], False
    else:
        if s.app_env == "production":
            raise HTTPException(503, "Online payments are not configured")
        oid, simulated = f"sim_{secrets.token_hex(8)}", True
    g = GatewayOrder(user_id=user_id, provider=s.payment_provider, provider_order_id=oid, amount_paise=amount_paise, is_simulated=simulated)
    db.add(g)
    db.commit()
    return {"gateway_order_id": oid, "amount_paise": amount_paise, "provider": s.payment_provider, "simulated": simulated,
            "key_id": s.razorpay_key_id if not simulated else None}


def _credit_once(db: Session, g: GatewayOrder, payment_id: str) -> None:
    g.status, g.provider_payment_id = "PAID", payment_id
    wallet.credit(db, g.user_id, g.amount_paise, "TOPUP", g.provider_order_id)


def confirm_topup(db: Session, user_id: int, order_id: str, payment_id: str, signature: str | None) -> GatewayOrder:
    s = get_settings()
    g = db.scalar(select(GatewayOrder).where(GatewayOrder.provider_order_id == order_id, GatewayOrder.user_id == user_id).with_for_update())
    if not g:
        raise HTTPException(404, "Payment not found")
    if g.status == "PAID":
        return g                     # idempotent: a retry never credits twice
    if g.is_simulated:
        if s.app_env == "production":
            raise HTTPException(403, "Simulated payments are disabled")
    else:
        expect = hmac.new(s.razorpay_key_secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
        if not signature or not hmac.compare_digest(expect, signature):
            g.status = "FAILED"
            db.commit()
            raise HTTPException(400, "Payment verification failed")
    _credit_once(db, g, payment_id)
    db.commit()
    return g
