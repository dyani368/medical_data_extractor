from types import SimpleNamespace

from fastapi import Header
from fastapi.testclient import TestClient
import pytest

from app import main
from app.core.security import get_current_user


class FakeRedis:
    def __init__(self):
        self.jobs = {}
        self.keys = {}

    def get(self, key):
        return self.keys.get(key)

    def setex(self, key, ttl, value):
        self.keys[key] = value

    def hset(self, key, mapping):
        self.jobs.setdefault(key, {}).update({name: str(value) for name, value in mapping.items()})

    def hgetall(self, key):
        return self.jobs.get(key, {})

    def ping(self):
        return True


@pytest.fixture
def client(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(main, "initialize_database", lambda: None)
    monkeypatch.setattr(main, "get_redis", lambda: redis)

    async def fake_worker(*args, **kwargs):
        pass

    monkeypatch.setattr(main, "process_document_job", fake_worker)

    def fake_user(x_test_user: int = Header(...)):
        return SimpleNamespace(id=x_test_user)

    main.app.dependency_overrides[get_current_user] = fake_user
    try:
        with TestClient(main.app) as test_client:
            yield test_client
    finally:
        main.app.dependency_overrides.clear()


def test_job_status_is_owner_only_and_retry_key_is_user_scoped(client):
    headers_42 = {"X-Test-User": "42", "Idempotency-Key": "same-key"}
    headers_99 = {"X-Test-User": "99", "Idempotency-Key": "same-key"}

    first = client.post("/upload", headers=headers_42, files={"file": ("a.txt", b"one", "text/plain")})
    retry = client.post("/upload", headers=headers_42, files={"file": ("a.txt", b"one", "text/plain")})
    other = client.post("/upload", headers=headers_99, files={"file": ("b.txt", b"two", "text/plain")})

    assert first.status_code == retry.status_code == other.status_code == 202
    own_job = first.json()["job_id"]
    assert retry.json()["job_id"] == own_job
    assert other.json()["job_id"] != own_job
    assert client.get(f"/jobs/{own_job}", headers=headers_42).status_code == 200
    assert client.get(f"/jobs/{own_job}", headers=headers_99).status_code == 404


def test_upload_rejects_invalid_text(client):
    headers = {"X-Test-User": "42"}
    invalid_utf8 = client.post(
        "/upload", headers=headers, files={"file": ("bad.txt", b"\xff", "text/plain")}
    )
    oversized = client.post(
        "/upload", headers=headers, files={"file": ("big.txt", b"x" * 1_000_001, "text/plain")}
    )
    assert invalid_utf8.status_code == 400
    assert oversized.status_code == 413
    empty = client.post(
        "/upload", headers=headers, files={"file": ("empty.txt", b"  ", "text/plain")}
    )
    assert empty.status_code == 400


def test_liveness_does_not_require_authentication(client):
    assert client.get("/health/live").json() == {"status": "ok"}


def test_readiness_reports_dependency_failure(client, monkeypatch):
    class BrokenEngine:
        def connect(self):
            raise OSError("database unavailable")

    monkeypatch.setattr(main, "engine", BrokenEngine())
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {"detail": "Dependency unavailable"}
