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
from app.services import document_assets
from app.services.document_assets import read_asset
from app.services.document_parser import extract_document_elements


def sanitize(text):
    # New queued jobs are already redacted; avoid loading spaCy in the worker.
    from app.core.sanitize import sanitize as redact
    return redact(text)


def _chunk_elements(elements):
    """Split text/table elements independently and retain ordered visual references."""
    if isinstance(elements, str):
        elements = [(None, elements)]
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    chunks = []
    for element in elements:
        if isinstance(element, (tuple, list)):
            page, text = element
            element = {"page_number": page, "element_type": "text", "text": text}
        if not isinstance(element, dict):
            continue
        page = element.get("page_number")
        kind = element.get("element_type", "text")
        title = element.get("section_title")
        if kind == "image":
            chunks.append({"page_number": page, "element_type": "image", "section_title": title,
                           "text": "", "context_text": element.get("context_text", ""),
                           "visual_assets": [{"asset_ref": element["asset_ref"],
                                                               "mime_type": element.get("image_mime", "image/png")}],
                           "bbox": element.get("bbox")})
            continue
        text = element.get("text", "").strip()
        if not text:
            continue
        for part in splitter.split_text(text):
            chunks.append({"page_number": page, "element_type": kind,
                           "section_title": title, "text": part, "visual_assets": [],
                           "bbox": element.get("bbox")})
    return chunks


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
        report(progress="5%", step="parsing source document")
        if isinstance(pages, dict) and pages.get("source_file_ref"):
            original = await asyncio.to_thread(read_asset, pages["source_file_ref"], user_id)
            elements = await asyncio.to_thread(extract_document_elements, original, filename,
                                              pages.get("content_type"))
            for element in elements:
                for field in ("text", "context_text"):
                    if element.get(field):
                        element[field] = await asyncio.to_thread(sanitize, element[field])
            stored_pages = await asyncio.to_thread(document_assets.persist_elements,
                                                   elements, user_id, job_id)
            if owner:
                await asyncio.to_thread(document_assets.preserve_source_upload,
                                        user_id, job_id, pages["source_file_ref"], filename)
                # Persist sanitized structure before deleting the raw upload. If the
                # worker dies before this transaction, the original remains retryable.
                queue.progress(job_id, owner, pages=stored_pages, progress="10%",
                               step="partitioned document")
                await asyncio.to_thread(document_assets.delete_source_upload, user_id,
                                        pages["source_file_ref"])
            pages = stored_pages
        if not owner:
            # Historical Redis jobs predate API-side sanitization.
            sanitized_pages = []
            for element in pages if not isinstance(pages, str) else [(None, pages)]:
                if isinstance(element, (tuple, list)):
                    page, text = element
                    sanitized_pages.append((page, await asyncio.to_thread(sanitize, text)))
                else:
                    item = dict(element)
                    for field in ("text", "context_text"):
                        if item.get(field):
                            item[field] = await asyncio.to_thread(sanitize, item[field])
                    sanitized_pages.append(item)
            pages = sanitized_pages
        report(progress="12%", step="preparing document passages")
        chunks = _chunk_elements(pages)
        if not chunks:
            raise ValueError("No processable text or visual content")
        results, successes, failures = [], 0, 0
        report(total_chunks=len(chunks), extraction_status="processing")
        for index, item in enumerate(chunks):
            report(progress=f"{int(20 + index / len(chunks) * 70)}%",
                   step=f"processing passage {index + 1}/{len(chunks)}")
            existing = None
            if owner:
                existing = db.scalar(select(document_model.Document).where(
                    document_model.Document.source_document_id == job_id,
                    document_model.Document.user_id == user_id,
                    document_model.Document.chunk_index == index))
            checkpoint = (db.scalar(select(result_model.Result).where(
                result_model.Result.document_id == existing.id).order_by(result_model.Result.id.desc()))
                if existing else None)
            # Successful captions and their extraction are durable checkpoints. A
            # failed image description is retried, while completed earlier passages
            # are not sent to the model again after worker recovery.
            if checkpoint and not (checkpoint.error_type == "ImageDescriptionFailed"):
                result = checkpoint
            else:
                content = item["text"]
                error = None
                if item["element_type"] == "image":
                    try:
                        asset = item["visual_assets"][0]
                        image_bytes = await asyncio.to_thread(read_asset, asset["asset_ref"], user_id)
                        description = await llm_provider.describe_image(
                            image_bytes, asset["mime_type"], page_number=item["page_number"],
                            section_title=item["section_title"], context_text=item.get("context_text", ""))
                        description = await asyncio.to_thread(sanitize, description)
                        context = item.get("context_text", "")
                        content = f"Image evidence on page {item['page_number']}: {description}"
                        if context:
                            content += f"\nNearby document text: {context}"
                    except Exception:
                        content = f"Image evidence on page {item['page_number']}; visual description unavailable."
                        error = "ImageDescriptionFailed"
                if item.get("section_title"):
                    content = f"Section: {item['section_title']}\n{content}"
                content = content[:20000]
                doc = existing or document_model.Document(
                    filename=filename, file_url=f"local_text_{uuid.uuid4()}", raw_content=content,
                    user_id=user_id, source_document_id=job_id, chunk_index=index,
                    page_number=item["page_number"], element_type=item["element_type"],
                    section_title=item.get("section_title"), visual_assets=item["visual_assets"] or None,
                    bbox=item.get("bbox"))
                if existing is not None:
                    # A failed visual description stores only a safe placeholder; on
                    # retry update the passage and embedding with the new caption.
                    doc.raw_content = content
                else:
                    db.add(doc)
                doc.element_type = item["element_type"]
                doc.section_title = item.get("section_title")
                doc.visual_assets = item["visual_assets"] or None
                doc.bbox = item.get("bbox")
                if error is None:
                    doc.embedding = await asyncio.to_thread(embed_text, content)
                    try:
                        parsed = document_schema.ExtractionResult.model_validate_json(
                            await llm_provider.generate(content))
                        outcome = "succeeded"
                    except Exception as exc:
                        parsed = llm_provider.fallback_result()
                        outcome, error = "failed", error or type(exc).__name__
                else:
                    parsed = llm_provider.fallback_result()
                    outcome = "failed"
                if existing is None:
                    db.flush()
                result = result_model.Result(document_id=doc.id, summary=parsed.summary,
                    category=parsed.category, key_entities=parsed.key_entities,
                    confidence=parsed.confidence, extraction_status=outcome, error_type=error)
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
