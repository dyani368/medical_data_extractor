from datetime import datetime, timedelta, UTC
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import HTTPException
import pytest
from app.services import ingestion_queue as queue
from app.models.ingestion_job_model import IngestionJob
from app.models.user_model import User


@pytest.fixture
def db_factory(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    User.__table__.create(engine)
    IngestionJob.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(queue, "SessionLocal", factory)
    monkeypatch.setattr(queue, "_notify_worker", lambda: None)
    yield factory
    engine.dispose()


def enqueue(user=42, key="key", content=b"sample"):
    return queue.enqueue([[1, "sample"]], "sample.pdf", user, key, content)


def expire_lease(factory, job_id):
    with factory() as db:
        job = db.get(IngestionJob, job_id)
        job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()


def test_durable_idempotency_is_atomic_user_scoped_and_content_bound(db_factory):
    first = enqueue()
    assert enqueue() == first
    assert enqueue(user=99) != first
    with pytest.raises(HTTPException) as error:
        enqueue(content=b"different")
    assert error.value.status_code == 409
    assert queue.get_status(first, 99) is None
    assert queue.get_status(first, 42)["status"] == "queued"


def test_worker_restart_reclaims_lease_and_fences_old_owner(db_factory):
    job_id = enqueue()
    assert queue.claim("old")["id"] == job_id
    assert queue.claim("another") is None
    expire_lease(db_factory, job_id)
    assert queue.claim("new")["id"] == job_id
    assert queue.get_status(job_id, 42)["attempts"] == 2
    with pytest.raises(queue.LeaseLost):
        queue.progress(job_id, "old", progress="100%")
    queue.progress(job_id, "new", status="completed", progress="100%")
    with db_factory() as db:
        assert db.get(IngestionJob, job_id).pages is None
    assert queue.claim("third") is None


def test_retry_limits_survive_repeated_worker_crashes(db_factory):
    job_id = enqueue()
    for index in range(queue.MAX_ATTEMPTS):
        assert queue.claim(str(index))["id"] == job_id
        expire_lease(db_factory, job_id)
    assert queue.claim("too-many") is None
    assert queue.get_status(job_id, 42)["status"] == "failed"
    with db_factory() as db:
        assert db.get(IngestionJob, job_id).pages is None


def test_failed_attempt_requeues_and_retention_does_not_delete_active_work(db_factory):
    job_id = enqueue()
    queue.claim("worker")
    queue.retry(job_id, "worker", RuntimeError())
    assert queue.get_status(job_id, 42)["status"] == "retrying"
    assert queue.claim("early") is None
    with db_factory() as db:
        job = db.get(IngestionJob, job_id)
        job.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        job.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    queue.cleanup()
    assert queue.claim("retry")["id"] == job_id
    queue.progress(job_id, "retry", status="completed")
    with db_factory() as db:
        db.get(IngestionJob, job_id).expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    queue.cleanup()
    with db_factory() as db:
        assert db.get(IngestionJob, job_id) is None


def test_worker_can_schedule_next_retry_without_constant_database_polling(db_factory):
    assert queue.next_due_delay() is None
    job_id = enqueue()
    queue.claim("worker")
    queue.retry(job_id, "worker", RuntimeError())
    delay = queue.next_due_delay()
    assert delay is not None and 0 < delay <= 5


def test_enqueue_wakes_worker_after_job_is_committed(db_factory, monkeypatch):
    observed = []

    def wake():
        with db_factory() as db:
            observed.append(db.scalar(select(IngestionJob.id)) is not None)

    monkeypatch.setattr(queue, "_notify_worker", wake)
    enqueue()
    assert observed == [True]
