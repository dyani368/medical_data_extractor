from functools import lru_cache
import threading
from app.core.config import settings

_inference_lock = threading.Lock()


@lru_cache(maxsize=1)
def get_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer('all-MiniLM-L6-v2')

def embed_text(text: str) -> list[float]:
    if settings.embedding_service_url:
        import httpx
        response = httpx.post(settings.embedding_service_url.rstrip('/') + '/embed',
            json={"text": text}, headers={"X-Worker-Key": settings.secret_key}, timeout=120)
        response.raise_for_status()
        vector = response.json()["embedding"]
        if len(vector) != 384 or any(type(value) not in (int, float) for value in vector):
            raise ValueError("Invalid embedding response")
        return vector
    # One model in the worker, safely shared by ingestion and query embedding.
    with _inference_lock:
        embedding = get_model().encode(text, show_progress_bar=False)
        return embedding.tolist()
