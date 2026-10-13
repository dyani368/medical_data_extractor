"""Small PostgreSQL queue: atomic claims, leases, bounded retries, and retention."""
from datetime import datetime, timedelta, UTC
import hashlib
import uuid
from sqlalchemy import select, or_, and_, delete, update
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from app.core.database import SessionLocal
from app.core.config import settings
from app.models.ingestion_job_model import IngestionJob

MAX_ATTEMPTS = 3
LEASE_SECONDS = 90
TERMINAL = ("completed", "completed_with_errors", "failed", "deleted")


class LeaseLost(Exception):
    pass


def enqueue(pages, filename, user_id, key, content):
    if key and len(key) > 200:
        raise HTTPException(400, "Idempotency key is too long")
    now = datetime.now(UTC)
    digest = hashlib.sha256(content).hexdigest()
    with SessionLocal() as db:
        # Expiry releases the key without deleting its retained job status.
        db.execute(update(IngestionJob).where(IngestionJob.user_id == user_id,
            IngestionJob.idempotency_expires_at <= now).values(idempotency_key=None))
        if key:
            existing = db.scalar(select(IngestionJob).where(
                IngestionJob.user_id == user_id, IngestionJob.idempotency_key == key))
            if existing:
                if existing.content_digest != digest:
                    raise HTTPException(409, "This idempotency key was already used for a different file")
                return existing.id
        job = IngestionJob(id=str(uuid.uuid4()), user_id=user_id, filename=filename,
            pages=pages, content_digest=digest, idempotency_key=key,
            idempotency_expires_at=now + timedelta(days=1), next_attempt_at=now,
            expires_at=now + timedelta(seconds=settings.job_retention_seconds))
        db.add(job)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            if not key:
                raise
            existing = db.scalar(select(IngestionJob).where(
                IngestionJob.user_id == user_id, IngestionJob.idempotency_key == key))
            if existing is None:
                raise
            if existing.content_digest != digest:
                raise HTTPException(409, "This idempotency key was already used for a different file")
            return existing.id
        return job.id


def get_status(job_id, user_id):
    with SessionLocal() as db:
        job = db.scalar(select(IngestionJob).where(IngestionJob.id == job_id,
            IngestionJob.user_id == user_id, IngestionJob.expires_at > datetime.now(UTC)))
        if job is None:
            return None
        return {name: getattr(job, name) for name in ("status", "progress", "step", "attempts",
            "extraction_status", "total_chunks", "successful_chunks", "failed_chunks", "result_ids", "error")}


def claim(owner):
    now = datetime.now(UTC)
    with SessionLocal() as db:
        job = db.scalar(select(IngestionJob).where(or_(
            and_(IngestionJob.status.in_(("queued", "retrying")), IngestionJob.next_attempt_at <= now),
            and_(IngestionJob.status == "processing", IngestionJob.lease_expires_at <= now)
        )).order_by(IngestionJob.created_at).with_for_update(skip_locked=True).limit(1))
        if job is None:
            return None
        if job.attempts >= MAX_ATTEMPTS:
            job.status, job.error, job.extraction_status = "failed", "RetryLimitExceeded", "failed"
            job.pages, job.lease_owner, job.lease_expires_at = None, None, None
            db.commit()
            return None
        job.status, job.lease_owner = "processing", owner
        job.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
        job.attempts += 1
        db.commit()
        return {"id": job.id, "pages": job.pages, "filename": job.filename, "user_id": job.user_id}


def lock_owned(db, job_id, owner):
    job = db.scalar(select(IngestionJob).where(IngestionJob.id == job_id,
        IngestionJob.lease_owner == owner, IngestionJob.status == "processing",
        IngestionJob.lease_expires_at > datetime.now(UTC)).with_for_update())
    if job is None:
        raise LeaseLost()
    return job


def progress(job_id, owner, **values):
    with SessionLocal() as db:
        job = lock_owned(db, job_id, owner)
        for key, value in values.items():
            setattr(job, key, value)
        if job.status in TERMINAL:
            job.pages, job.lease_owner, job.lease_expires_at = None, None, None
            job.expires_at = datetime.now(UTC) + timedelta(seconds=settings.job_retention_seconds)
        db.commit()


def heartbeat(job_id, owner):
    with SessionLocal() as db:
        job = lock_owned(db, job_id, owner)
        job.lease_expires_at = datetime.now(UTC) + timedelta(seconds=LEASE_SECONDS)
        db.commit()


def retry(job_id, owner, error):
    with SessionLocal() as db:
        job = lock_owned(db, job_id, owner)
        job.error = type(error).__name__
        job.status = "failed" if job.attempts >= MAX_ATTEMPTS else "retrying"
        job.next_attempt_at = datetime.now(UTC) + timedelta(seconds=5 * job.attempts)
        job.lease_owner, job.lease_expires_at = None, None
        if job.status == "failed":
            job.pages, job.extraction_status = None, "failed"
        db.commit()


def cleanup():
    now = datetime.now(UTC)
    with SessionLocal() as db:
        db.execute(delete(IngestionJob).where(IngestionJob.status.in_(TERMINAL),
                                              IngestionJob.expires_at <= now))
        db.execute(update(IngestionJob).where(IngestionJob.idempotency_expires_at <= now)
                   .values(idempotency_key=None))
        db.commit()


def mark_deleted(db, job_id, user_id):
    job = db.scalar(select(IngestionJob).where(IngestionJob.id == job_id,
        IngestionJob.user_id == user_id).with_for_update())
    if job:
        if job.status not in TERMINAL:
            raise HTTPException(409, "Wait for document processing to finish before deleting it")
        job.status, job.pages, job.idempotency_key = "deleted", None, None
