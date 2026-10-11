import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document_model import Document
from app.models.result_model import Result


def parse_arguments(raw: str) -> dict:
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def get_extraction_result(document_id: int, user_id: int, db: Session):
    row = db.execute(
        select(Document, Result).join(Result, Result.document_id == Document.id)
        .where(Document.id == document_id, Document.user_id == user_id)
        .order_by(Result.created_at.desc(), Result.id.desc()).limit(1)
    ).first()
    if row is None:
        return "No extraction result was found for that document in your records.", []
    document, result = row
    content = (
        f"[doc:{document.id}] Stored extraction: {result.summary}\n"
        f"Category: {result.category}\nExtracted entities: {json.dumps(result.key_entities, ensure_ascii=False)}\n"
        f"Confidence: {result.confidence:.2f}"
    )
    return content, [{"document_id": document.id, "filename": document.filename}]


def get_related_document_chunks(document_id: int, user_id: int, db: Session):
    document = db.execute(select(Document).where(
        Document.id == document_id, Document.user_id == user_id
    )).scalar_one_or_none()
    if document is None:
        return []
    stem = document.filename.rsplit("_chunk_", 1)[0]
    return db.execute(select(Document).where(
        Document.user_id == user_id,
        Document.filename.startswith(stem + "_chunk_", autoescape=True),
    ).order_by(Document.id).limit(5)).scalars().all()
