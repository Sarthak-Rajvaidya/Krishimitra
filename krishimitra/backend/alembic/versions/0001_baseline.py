"""Baseline schema.

Creates every table from the current SQLAlchemy metadata. This is a BASELINE snapshot, not a hand-written
diff: for later schema changes run `alembic revision --autogenerate -m "describe change"` and review the result.

Revision ID: 0001
"""
from alembic import op

from app.db.base import Base
import app.models  # noqa: F401

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
