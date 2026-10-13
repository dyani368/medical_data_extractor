from fastapi.testclient import TestClient
from app import worker
from app.core import embeddings
from app.core.config import settings


def test_private_embedding_endpoint_requires_key(monkeypatch):
    monkeypatch.setattr(worker, "embed_text", lambda text: [0.1] * 384)
    with TestClient(worker.embedding_app) as client:
        assert client.post("/embed", json={"text": "sample"}).status_code == 403
        response = client.post("/embed", json={"text": "sample"}, headers={"X-Worker-Key": settings.secret_key})
        assert response.status_code == 200
        assert len(response.json()["embedding"]) == 384
        assert client.get("/docs").status_code == 404


def test_api_embedding_client_does_not_load_a_second_model(monkeypatch):
    import httpx
    monkeypatch.setattr(settings, "embedding_service_url", "http://worker:8001")
    monkeypatch.setattr(embeddings, "get_model", lambda: (_ for _ in ()).throw(AssertionError("Loaded API model")))
    def post(url, **kwargs):
        assert url == "http://worker:8001/embed"
        assert kwargs["headers"]["X-Worker-Key"] == settings.secret_key
        return httpx.Response(200, json={"embedding": [0.1] * 384}, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", post)
    assert len(embeddings.embed_text("sample")) == 384
