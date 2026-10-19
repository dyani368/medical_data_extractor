"""Store element type, section, and private visual evidence references."""
from alembic import op
import sqlalchemy as sa

revision = "20261014_multimodal"
down_revision = "20261013_durable_jobs"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("documents", sa.Column("element_type", sa.String(length=20), nullable=False,
                                           server_default="text"))
    op.add_column("documents", sa.Column("section_title", sa.String(length=300), nullable=True))
    op.add_column("documents", sa.Column("visual_assets", sa.JSON(), nullable=True))
    op.alter_column("documents", "element_type", server_default=None)


def downgrade():
    op.drop_column("documents", "visual_assets")
    op.drop_column("documents", "section_title")
    op.drop_column("documents", "element_type")
