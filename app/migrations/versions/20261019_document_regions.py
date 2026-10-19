"""Retain PDF element regions for source-to-extraction review."""
from alembic import op
import sqlalchemy as sa

revision = "20261019_document_regions"
down_revision = "20261014_multimodal"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("documents", sa.Column("bbox", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("documents", "bbox")
