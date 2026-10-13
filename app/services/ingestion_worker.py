"""Checkpointed ingestion, executed by app.worker in its own process."""
import asyncio
import json
import uuid
from sqlalchemy import select
from langchain_text_splitters import RecursiveCharacterTextSplitter
from app.core.database import SessionLocal
from app.core.redis_client import get_redis
from app.core.embeddings import embed_text
from app.core.config import settings
from app.models import document_model, result_model
from app.schemas import document_schema
from app.services import ingestion_queue as queue


def sanitize(text):
    # New queued jobs are already redacted; avoid loading spaCy in the worker.
    from app.core.sanitize import sanitize as redact
    return redact(text)


async def process_document_job(job_id, pages, filename, user_id, llm_provider, owner=None):
    redis = get_redis() if owner is None else None

    def report(**values):
        if owner:
            queue.progress(job_id, owner, **values)
        else:
            redis.hset(f"job:{job_id}", mapping={
                key: json.dumps(value) if isinstance(value, list) else value
                for key, value in values.items()})

    db = SessionLocal()
    try:
        report(progress="10%", step="sanitizing")
        if isinstance(pages, str):
            pages = [(None, pages)]
        # Durable payloads were sanitized before enqueue; legacy jobs still need it.
        sanitized = pages if owner else [(page, await asyncio.to_thread(sanitize, text)) for page, text in pages]
        splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
        chunks = [(page, chunk) for page, text in sanitized for chunk in splitter.split_text(text)]
        if not chunks:
            raise ValueError("No processable text")
        results, successes, failures = [], 0, 0
        report(total_chunks=len(chunks), extraction_status="processing")
        for index, (page, chunk) in enumerate(chunks):
            report(progress=f"{int(20 + index / len(chunks) * 70)}%",
                   step=f"processing chunk {index + 1}/{len(chunks)}")
            existing = None
            if owner:
                existing = db.scalar(select(document_model.Document).where(
                    document_model.Document.source_document_id == job_id,
                    document_model.Document.user_id == user_id,
                    document_model.Document.chunk_index == index))
            checkpoint = (db.scalar(select(result_model.Result).where(
                result_model.Result.document_id == existing.id).order_by(result_model.Result.id.desc()))
                if existing else None)
            if checkpoint:
                result = checkpoint
            else:
                doc = existing or document_model.Document(filename=filename,
                    file_url=f"local_text_{uuid.uuid4()}", raw_content=chunk, user_id=user_id,
                    source_document_id=job_id, chunk_index=index, page_number=page)
                if existing is None:
                    doc.embedding = await asyncio.to_thread(embed_text, chunk)
                    db.add(doc)
                    db.flush()
                outcome, error = "succeeded", None
                try:
                    parsed = document_schema.ExtractionResult.model_validate_json(await llm_provider.generate(chunk))
                except Exception as exc:
                    parsed = llm_provider.fallback_result()
                    outcome, error = "failed", type(exc).__name__
                result = result_model.Result(document_id=doc.id, summary=parsed.summary,
                    category=parsed.category, key_entities=parsed.key_entities, confidence=parsed.confidence,
                    extraction_status=outcome, error_type=error)
                db.add(result)
                if owner:
                    # Fence stale workers before committing after lease recovery.
                    queue.lock_owned(db, job_id, owner)
                db.commit()
            results.append(result.id)
            if result.extraction_status == "succeeded":
                successes += 1
            else:
                failures += 1
            report(successful_chunks=successes, failed_chunks=failures)
        outcome = "succeeded" if failures == 0 else "failed" if successes == 0 else "partial"
        report(status="completed" if failures == 0 else "completed_with_errors", progress="100%",
               result_ids=results, successful_chunks=successes, failed_chunks=failures,
               extraction_status=outcome, step="finished")
    except Exception:
        db.rollback()
        if owner:
            raise
        report(status="failed", extraction_status="failed", error="IngestionError")
    finally:
        if redis:
            redis.expire(f"job:{job_id}", settings.job_retention_seconds)
        db.close()
