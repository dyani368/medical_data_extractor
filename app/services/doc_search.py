from sqlalchemy.orm import Session
from sqlalchemy import select

from app.core.embeddings import embed_text
from app.models import document_model

def generate_relevant_docs(query: str, limit: int, user_id: int,db: Session, threshold: float = 0.45):
    query_vector = embed_text(query)
    distance = document_model.Document.embedding.cosine_distance(query_vector)
    stmt = select(document_model.Document).where(document_model.Document.user_id == user_id,
           distance<=threshold).order_by(distance).limit(limit)
    
    similar_docs = db.execute(stmt).scalars().all()
    
    return similar_docs