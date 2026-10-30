"""Bind document chat history to its selected upload."""

from alembic import op
import sqlalchemy as sa

revision = "20261030_conversation_scope"
down_revision = "20261019_document_regions"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("conversations", sa.Column("source_document_id", sa.String(), nullable=True))
    op.create_index("ix_conversations_source_document_id", "conversations", ["source_document_id"])


def downgrade():
    op.drop_index("ix_conversations_source_document_id", table_name="conversations")
    op.drop_column("conversations", "source_document_id")
