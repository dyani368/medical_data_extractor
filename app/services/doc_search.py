from sqlalchemy.orm import Session
from sqlalchemy import select, func

from app.core.embeddings import embed_text
from app.models import document_model

def fuse_rankings(vector_docs, keyword_docs, limit):
    """Reciprocal rank fusion: combine rankings without comparing unlike scores."""
    scores, documents = {}, {}
    for ranking in (vector_docs, keyword_docs):
        for rank, doc in enumerate(ranking, start=1):
            documents[doc.id] = doc
            scores[doc.id] = scores.get(doc.id, 0.0) + 1.0 / (60 + rank)
    ordered = sorted(scores, key=lambda doc_id: (-scores[doc_id], doc_id))
    return [documents[doc_id] for doc_id in ordered[:limit]]

def generate_relevant_docs(query: str, limit: int, user_id: int, db: Session, threshold: float | None = None):
    """Return ranked candidates, not a claim that they contain the answer.

    A fixed MiniLM cosine cutoff rejected real answer passages. By default search
    combines bounded vector and PostgreSQL full-text rankings; the answer model
    must still verify support. Explicit thresholds remain available for experiments.
    """
    limit = max(1, min(limit, 10))
    candidate_limit = max(20, limit)
    query_vector = embed_text(query)
    distance = document_model.Document.embedding.cosine_distance(query_vector)
    stmt = select(document_model.Document).where(
        document_model.Document.user_id == user_id,
        document_model.Document.embedding.is_not(None),
    )
    if threshold is not None:
        stmt = stmt.where(distance <= threshold)
        return db.execute(stmt.order_by(distance, document_model.Document.id).limit(limit)).scalars().all()
    vector_docs = db.execute(stmt.order_by(distance, document_model.Document.id).limit(candidate_limit)).scalars().all()
    search_text = func.regexp_replace(document_model.Document.filename, '[^a-zA-Z0-9]+', ' ', 'g') + ' ' + document_model.Document.raw_content
    lexemes = func.to_tsvector('english', search_text)
    terms = func.plainto_tsquery('english', query)
    keyword_stmt = select(document_model.Document).where(
        document_model.Document.user_id == user_id, lexemes.op('@@')(terms)
    ).order_by(func.ts_rank_cd(lexemes, terms).desc(), document_model.Document.id).limit(candidate_limit)
    keyword_docs = db.execute(keyword_stmt).scalars().all()
    return fuse_rankings(vector_docs, keyword_docs, limit)
