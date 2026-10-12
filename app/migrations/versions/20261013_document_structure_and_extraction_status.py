"""Track uploaded-document chunk structure and extraction outcomes."""
from alembic import op
import sqlalchemy as sa


revision = "20261013_doc_structure"
down_revision = "20261011_initial"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    document_columns = {column["name"] for column in inspector.get_columns("documents")}
    result_columns = {column["name"] for column in inspector.get_columns("results")}
    if "source_document_id" not in document_columns:
        op.add_column("documents", sa.Column("source_document_id", sa.String(length=36), nullable=True))
    if "chunk_index" not in document_columns:
        op.add_column("documents", sa.Column("chunk_index", sa.Integer(), nullable=True))
    if "page_number" not in document_columns:
        op.add_column("documents", sa.Column("page_number", sa.Integer(), nullable=True))
    if "ix_documents_source_document_id" not in {index["name"] for index in inspector.get_indexes("documents")}:
        op.create_index("ix_documents_source_document_id", "documents", ["source_document_id"])

    if "extraction_status" not in result_columns:
        op.add_column("results", sa.Column(
            "extraction_status", sa.String(length=20), server_default=sa.text("'succeeded'"), nullable=False
        ))
    if "error_type" not in result_columns:
        op.add_column("results", sa.Column("error_type", sa.String(length=100), nullable=True))
    op.execute("""
        UPDATE results
        SET extraction_status = 'failed', error_type = 'HistoricalFallback'
        WHERE summary ILIKE 'LLM processing failed%'
    """)


def downgrade():
    # Retain migrated extraction metadata and document structure with existing records.
    pass
