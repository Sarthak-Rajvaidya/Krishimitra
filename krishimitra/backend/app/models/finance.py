import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FinTxnType(str, enum.Enum):
    SALE = "SALE"              # net item revenue excl. GST (credit)
    GST_COLLECTED = "GST_COLLECTED"
    DELIVERY_FEE = "DELIVERY_FEE"
    DISCOUNT = "DISCOUNT"
    COGS = "COGS"
    REFUND = "REFUND"                      # ex-GST item revenue reversed
    GST_REFUNDED = "GST_REFUNDED"
    DELIVERY_FEE_REFUNDED = "DELIVERY_FEE_REFUNDED"
    COGS_REVERSAL = "COGS_REVERSAL"
    EXPENSE = "EXPENSE"
    COMMISSION = "COMMISSION"                    # platform commission on supplier orders, recognised on delivery
    COMMISSION_REVERSAL = "COMMISSION_REVERSAL"


class FinancialTransaction(Base):
    """Append-only ledger. Rows are never updated or deleted (enforced at service layer)."""
    __tablename__ = "financial_transactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    txn_type: Mapped[FinTxnType] = mapped_column(Enum(FinTxnType), index=True)
    amount_paise: Mapped[int] = mapped_column(Integer)  # always positive; type defines direction
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), index=True)
    reference: Mapped[str | None] = mapped_column(String(80))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Expense(Base):
    __tablename__ = "expenses"
    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(60), index=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    amount_paise: Mapped[int] = mapped_column(Integer)
    incurred_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    recorded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
