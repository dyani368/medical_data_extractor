"""Baseline the existing SQLAlchemy schema under Alembic tracking.

This is the one-time baseline for the demo's existing tables. create_all is
idempotent and leaves existing tables and data intact. Future migrations should
use explicit Alembic operations and must not modify this baseline.
"""
from alembic import op

from app import models  # noqa: F401 -- register model metadata
from app.core.database import Base

revision = "20261011_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    Base.metadata.create_all(bind=op.get_bind())


def downgrade():
    # Baseline downgrade intentionally keeps existing user data and tables.
    # Destructive schema removal must be an explicit, separate operation.
    pass
