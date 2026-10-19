from types import SimpleNamespace

from fastapi import Header
from fastapi.testclient import TestClient
import pytest

from app import main
from app.core.security import get_current_user
from app.core.database import get_db
from app.services.document_parser import MAX_UPLOAD_BYTES


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
    monkeypatch.setattr(main.document_assets, "persist_source_upload",
                        lambda content, user_id, source_id: f"{user_id}/{source_id}.upload")
    monkeypatch.setattr(main.document_assets, "delete_source_upload", lambda *args: None)

    def enqueue(pages, filename, user_id, key, content, source_document_id=None):
        import uuid
        existing = redis.get(f"idempotency:{user_id}:{key}") if key else None
        if existing:
            return existing
        job_id = str(uuid.uuid4())
        redis.hset(f"job:{job_id}", mapping={"status": "queued", "user_id": user_id})
        if key:
            redis.setex(f"idempotency:{user_id}:{key}", 86400, job_id)
        return job_id

    monkeypatch.setattr(main.ingestion_queue, "enqueue", enqueue)
    monkeypatch.setattr(main.ingestion_queue, "get_status", lambda *args: None)

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
        "/upload", headers=headers, files={"file": ("big.txt", b"x" * (MAX_UPLOAD_BYTES + 1), "text/plain")}
    )
    assert invalid_utf8.status_code == 400
    assert oversized.status_code == 413
    empty = client.post(
        "/upload", headers=headers, files={"file": ("empty.txt", b"  ", "text/plain")}
    )
    assert empty.status_code == 400


def test_pdf_upload_is_queued_without_parsing_in_api_process(client):
    response = client.post(
        "/upload", headers={"X-Test-User": "42"},
        files={"file": ("large.pdf", b"%PDF-1.7 worker parses this", "application/pdf")},
    )
    assert response.status_code == 202
    assert response.json()["status"] == "accepted"


def test_liveness_does_not_require_authentication(client):
    assert client.get("/health/live").json() == {"status": "ok"}


def test_bundled_sample_preview_is_not_a_general_file_reader(client):
    preview = client.get("/samples/cardiovascular-followup/pages/1/preview")
    missing = client.get("/samples/private-record/pages/1/preview")
    assert preview.status_code == 200 and preview.content.startswith(b"\x89PNG")
    assert missing.status_code == 404


def test_readiness_reports_dependency_failure(client, monkeypatch):
    class BrokenEngine:
        def connect(self):
            raise OSError("database unavailable")

    monkeypatch.setattr(main, "engine", BrokenEngine())
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {"detail": "Dependency unavailable"}


def test_original_document_preview_is_account_scoped(client, monkeypatch, tmp_path):
    import fitz
    import uuid
    from unittest.mock import MagicMock
    from fastapi import HTTPException

    source_id = str(uuid.uuid4())
    pdf_path = tmp_path / "source.pdf"
    pdf = fitz.open()
    pdf.new_page().insert_text((40, 60), "Account 42 example")
    pdf_path.write_bytes(pdf.tobytes())

    def owned_rows(document_id, user_id, db):
        if document_id != source_id or user_id != 42:
            raise HTTPException(status_code=404, detail="Document not found")
        return [SimpleNamespace(source_document_id=source_id, filename="record.pdf",
                                id=9, chunk_index=0, page_number=1,
                                raw_content="Account 42 example", element_type="text",
                                section_title=None, bbox=[40, 50, 180, 70],
                                visual_assets=None, created_at="2026-10-19T00:00:00Z")]

    monkeypatch.setattr(main, "_document_group_rows", owned_rows)
    monkeypatch.setattr(main.document_assets, "resolve_document_source", lambda *args: pdf_path)
    main.app.dependency_overrides[get_db] = lambda: MagicMock()
    try:
        own = client.get(f"/documents/{source_id}/source", headers={"X-Test-User": "42"})
        other = client.get(f"/documents/{source_id}/source", headers={"X-Test-User": "99"})
        assert own.status_code == 200
        assert own.headers["content-type"] == "application/pdf"
        assert other.status_code == 404
        detail = client.get(f"/documents/{source_id}", headers={"X-Test-User": "42"}).json()
        assert detail["page_count"] == 1
        assert detail["pages"][0]["width"] > 0
        assert detail["chunks"][0]["bbox"] == [40, 50, 180, 70]
        page = client.get(f"/documents/{source_id}/pages/1/preview", headers={"X-Test-User": "42"})
        other_page = client.get(f"/documents/{source_id}/pages/1/preview", headers={"X-Test-User": "99"})
        assert page.status_code == 200 and page.content.startswith(b"\x89PNG")
        assert page.headers["cache-control"] == "private, no-store"
        assert other_page.status_code == 404
    finally:
        main.app.dependency_overrides.pop(get_db, None)
