from sqlalchemy.orm import Session
from sqlalchemy import select

from app.core.embeddings import embed_text
from app.models import document_model

def generate_relevant_docs(query: str, limit: int, db: Session):
    query_vector = embed_text(query)
    stmt = select(document_model.Document).order_by(
        document_model.Document.embedding.cosine_distance(query_vector)
    ).limit(limit)
    
    similar_docs = db.execute(stmt).scalars().all()
    
    return similar_docs