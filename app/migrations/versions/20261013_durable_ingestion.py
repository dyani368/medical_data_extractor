"""Add the durable ingestion queue without modifying existing records."""
from alembic import op
import sqlalchemy as sa

revision = "20261013_durable_jobs"
down_revision = "20261013_doc_structure"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("ingestion_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("pages", sa.JSON(), nullable=True),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=True),
        sa.Column("idempotency_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("progress", sa.String(10), nullable=False),
        sa.Column("step", sa.String(100)),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.String(36)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("extraction_status", sa.String(20), nullable=False),
        sa.Column("total_chunks", sa.Integer(), nullable=False),
        sa.Column("successful_chunks", sa.Integer(), nullable=False),
        sa.Column("failed_chunks", sa.Integer(), nullable=False),
        sa.Column("result_ids", sa.JSON(), nullable=False),
        sa.Column("error", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_job_user_key"))
    for column in ("user_id", "status", "lease_expires_at", "expires_at"):
        op.create_index(f"ix_ingestion_jobs_{column}", "ingestion_jobs", [column])


def downgrade():
    op.drop_table("ingestion_jobs")
