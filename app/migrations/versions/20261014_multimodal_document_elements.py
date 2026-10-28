"""Store element type, section, and private visual evidence references."""
from alembic import op
import sqlalchemy as sa

revision = "20261014_multimodal"
down_revision = "20261013_durable_jobs"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("documents")}
    if "element_type" not in columns:
        op.add_column("documents", sa.Column("element_type", sa.String(length=20), nullable=False,
                                               server_default="text"))
        op.alter_column("documents", "element_type", server_default=None)
    if "section_title" not in columns:
        op.add_column("documents", sa.Column("section_title", sa.String(length=300), nullable=True))
    if "visual_assets" not in columns:
        op.add_column("documents", sa.Column("visual_assets", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("documents", "visual_assets")
    op.drop_column("documents", "section_title")
    op.drop_column("documents", "element_type")
