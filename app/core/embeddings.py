from functools import lru_cache


@lru_cache(maxsize=1)
def get_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer('all-MiniLM-L6-v2')

def embed_text(text: str) -> list[float]:
    embedding = get_model().encode(text)
    return embedding.tolist()
