"""Wallet ledger. Balance changes are single conditional UPDATEs, so concurrent requests cannot overdraw."""
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import Wallet, WalletTxn


def get_wallet(db: Session, user_id: int) -> Wallet:
    w = db.scalar(select(Wallet).where(Wallet.user_id == user_id))
    if not w:
        w = Wallet(user_id=user_id, balance_paise=0)
        db.add(w)
        db.flush()
    return w


def _log(db: Session, user_id: int, kind: str, delta: int, ref: str | None) -> None:
    bal = db.scalar(select(Wallet.balance_paise).where(Wallet.user_id == user_id)) or 0
    db.add(WalletTxn(user_id=user_id, kind=kind, amount_paise=delta, balance_after_paise=bal, reference=ref, created_at=utcnow()))


def credit(db: Session, user_id: int, amount: int, kind: str, ref: str | None = None) -> None:
    if amount <= 0:
        return
    get_wallet(db, user_id)
    db.execute(update(Wallet).where(Wallet.user_id == user_id).values(balance_paise=Wallet.balance_paise + amount))
    _log(db, user_id, kind, amount, ref)


def debit(db: Session, user_id: int, amount: int, kind: str, ref: str | None = None, *, strict: bool = True) -> int:
    """Returns the amount actually debited. strict=True raises 402 when funds are short; strict=False debits what is available."""
    if amount <= 0:
        return 0
    get_wallet(db, user_id)
    res = db.execute(update(Wallet).where(Wallet.user_id == user_id, Wallet.balance_paise >= amount)
                     .values(balance_paise=Wallet.balance_paise - amount))
    if res.rowcount == 1:
        _log(db, user_id, kind, -amount, ref)
        return amount
    if strict:
        raise HTTPException(402, "Insufficient wallet balance")
    avail = db.scalar(select(Wallet.balance_paise).where(Wallet.user_id == user_id)) or 0
    return debit(db, user_id, avail, kind, ref, strict=True) if avail > 0 else 0
