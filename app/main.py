from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File, Header, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import select, text, desc
from typing import Annotated
from pydantic import ValidationError

from fastapi.security import OAuth2PasswordRequestForm
from datetime import timedelta

from app.models import document_model, result_model, user_model, conversation_model, audit_model
from app.models.document_model import Document
from app.models.result_model import Result
from app.models.conversation_model import Conversation, Message
from app.schemas import document_schema, user_schema
from app.services import doc_search
from app.services.agent_service import run_clinical_agent, run_clinical_agent_stream

from app.core.database import engine, get_db
from app.core.security import get_current_user, create_access_token, verify_password, get_password_hash
from app.core.config import settings
from app.core.embeddings import embed_text
from app.core.async_work import run_blocking
from app.core.sanitize import sanitize

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.providers.openai_provider import OpenAIProvider
from app.routers import auth
from app.services import ingestion_queue
from app.services.document_parser import MAX_UPLOAD_BYTES, validate_document_upload
from app.services import document_assets
from app.core.redis_client import get_redis

import uuid
import os
import asyncio
import json
from dotenv import load_dotenv


def initialize_database():
    from alembic import command
    from alembic.config import Config

    migration_config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    migration_config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
    command.upgrade(migration_config, "head")

@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    yield

app = FastAPI(lifespan=lifespan)
app.include_router(auth.router)

@app.get("/health/live")
def live():
    return {"status": "ok"}

@app.get("/health/ready")
def ready():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        get_redis().ping()
    except Exception:
        raise HTTPException(status_code=503, detail="Dependency unavailable")
    return {"status": "ready"}

load_dotenv()

llm_provider = OpenAIProvider()

async def run_extraction_pipeline(text: str, filename: str, db: Session, user_id: int):
    text = await run_blocking(sanitize, text)
    new_doc = document_model.Document(
        filename=filename,
        file_url=f"local_text_{uuid.uuid4()}",
        raw_content=text,
        user_id=user_id
    )

    new_doc.embedding = await run_blocking(embed_text, text)
    db.add(new_doc)
    db.flush()

    try:
        raw_json_string = await llm_provider.generate(text)
        parsed_data = document_schema.ExtractionResult.model_validate_json(raw_json_string)
    except ValidationError:
        db.rollback()
        raise HTTPException(status_code=502, detail="Extraction provider returned invalid output")
    except Exception:
        parsed_data = llm_provider.fallback_result()

    new_result = result_model.Result(
        document_id=new_doc.id,
        summary=parsed_data.summary,
        category=parsed_data.category,
        key_entities=parsed_data.key_entities,
        confidence=parsed_data.confidence
    )

    db.add(new_result)
    db.commit()

    return new_result

@app.post("/process", response_model=document_schema.ResultResponse)
async def process_document(
    request: document_schema.DocumentRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[user_model.User, Depends(get_current_user)]
):
    return await run_extraction_pipeline(request.text, "api_upload.txt", db, current_user.id)

@app.post("/upload", status_code=202)
async def upload_document(
    current_user: Annotated[user_model.User, Depends(get_current_user)],
    file: UploadFile = File(...),
    idempotency_key: str = Header(None)
):
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="File is too large")
    await asyncio.to_thread(validate_document_upload, content, file.filename, file.content_type)
    safe_filename = await asyncio.to_thread(sanitize, os.path.basename(file.filename or "document"))
    source_document_id = str(uuid.uuid4())
    source_ref = await asyncio.to_thread(document_assets.persist_source_upload, content,
                                         current_user.id, source_document_id)
    payload = {"source_file_ref": source_ref, "content_type": file.content_type}
    try:
        job_id = await asyncio.to_thread(ingestion_queue.enqueue, payload, safe_filename,
                                        current_user.id, idempotency_key, content, source_document_id)
    except Exception:
        await asyncio.to_thread(document_assets.delete_source_upload, current_user.id, source_ref)
        raise

    return {"status": "accepted", "job_id": job_id, "document_id": job_id,
            "message": "Document ingestion queued for async processing."}

@app.get("/jobs/{job_id}")
async def get_job_status(
    job_id: str,
    current_user: Annotated[user_model.User, Depends(get_current_user)],
):
    durable_status = await asyncio.to_thread(ingestion_queue.get_status, job_id, current_user.id)
    if durable_status is not None:
        return durable_status
    redis = get_redis()
    job_data = redis.hgetall(f"job:{job_id}")
    if not job_data or job_data.get("user_id") != str(current_user.id):
        raise HTTPException(status_code=404, detail="Job not found")
    payload = {key: value for key, value in job_data.items() if key != "user_id"}
    try:
        payload["result_ids"] = json.loads(payload.get("result_ids", "[]"))
    except (TypeError, json.JSONDecodeError):
        payload["result_ids"] = []
    for key in ("total_chunks", "successful_chunks", "failed_chunks"):
        if key in payload:
            payload[key] = int(payload[key])
    return payload


def _document_group_rows(document_id: str, user_id: int, db: Session):
    if document_id.startswith("legacy-"):
        try:
            legacy_id = int(document_id.removeprefix("legacy-"))
        except ValueError:
            raise HTTPException(status_code=404, detail="Document not found")
        rows = db.execute(select(Document).where(
            Document.id == legacy_id, Document.user_id == user_id,
            Document.source_document_id.is_(None),
        ).order_by(Document.id)).scalars().all()
    else:
        rows = db.execute(select(Document).where(
            Document.source_document_id == document_id, Document.user_id == user_id,
        ).order_by(Document.chunk_index, Document.id)).scalars().all()
    if not rows:
        raise HTTPException(status_code=404, detail="Document not found")
    return rows


@app.get("/documents")
def list_documents(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[user_model.User, Depends(get_current_user)],
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    rows = db.execute(
        select(Document.source_document_id, Document.id, Document.filename, Document.created_at,
               Result.extraction_status)
        .outerjoin(Result, Result.document_id == Document.id)
        .where(Document.user_id == current_user.id)
        .order_by(desc(Document.created_at), desc(Document.id))
    ).all()
    groups = {}
    for source_id, chunk_id, filename, created_at, extraction_status in rows:
        group_id = source_id or f"legacy-{chunk_id}"
        group = groups.setdefault(group_id, {
            "document_id": group_id, "filename": filename, "created_at": created_at,
            "chunk_ids": set(), "succeeded": set(), "failed": set(), "pending": set(),
        })
        group["chunk_ids"].add(chunk_id)
        if extraction_status == "failed":
            group["failed"].add(chunk_id)
        elif extraction_status == "succeeded":
            group["succeeded"].add(chunk_id)
        else:
            group["pending"].add(chunk_id)

    items = []
    for group in groups.values():
        chunk_count = len(group["chunk_ids"])
        failures = len(group["failed"])
        successes = len(group["succeeded"])
        extraction_status = ("failed" if failures == chunk_count else
                             "partial" if failures else
                             "succeeded" if successes == chunk_count else "pending")
        items.append({
            "document_id": group["document_id"], "filename": group["filename"],
            "created_at": group["created_at"], "chunk_count": chunk_count,
            "successful_extractions": successes, "failed_extractions": failures,
            "extraction_status": extraction_status,
        })
    return {"items": items[offset:offset + limit], "total": len(items), "limit": limit, "offset": offset}


@app.get("/documents/{document_id}")
def get_document(
    document_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[user_model.User, Depends(get_current_user)],
):
    chunks = _document_group_rows(document_id, current_user.id, db)
    return {
        "document_id": chunks[0].source_document_id or f"legacy-{chunks[0].id}",
        "filename": chunks[0].filename,
        "created_at": chunks[0].created_at,
        "chunks": [{
            "id": chunk.id, "chunk_index": chunk.chunk_index, "page_number": chunk.page_number,
            "content": chunk.raw_content, "element_type": chunk.element_type,
            "section_title": chunk.section_title,
            "visuals": [{"url": f"/chunks/{chunk.id}/visuals/{index}",
                         "mime_type": asset.get("mime_type", "image/png")}
                        for index, asset in enumerate(chunk.visual_assets or [])],
        } for chunk in chunks],
    }


@app.get("/documents/{document_id}/extraction")
def get_document_extractions(
    document_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[user_model.User, Depends(get_current_user)],
):
    chunks = _document_group_rows(document_id, current_user.id, db)
    chunk_ids = [chunk.id for chunk in chunks]
    results = db.execute(select(Result).where(Result.document_id.in_(chunk_ids))
                         .order_by(Result.document_id, Result.created_at.desc(), Result.id.desc())).scalars().all()
    latest = {}
    for result in results:
        latest.setdefault(result.document_id, result)
    return {
        "document_id": chunks[0].source_document_id or f"legacy-{chunks[0].id}",
        "filename": chunks[0].filename,
        "items": [{
            "document_id": chunk.id, "chunk_index": chunk.chunk_index, "page_number": chunk.page_number,
            "status": latest[chunk.id].extraction_status if chunk.id in latest else "pending",
            "error_type": latest[chunk.id].error_type if chunk.id in latest else None,
            "result": ({
                "summary": latest[chunk.id].summary, "category": latest[chunk.id].category,
                "key_entities": latest[chunk.id].key_entities,
                "confidence": latest[chunk.id].confidence,
            } if chunk.id in latest else None),
        } for chunk in chunks],
    }


@app.get("/chunks/{chunk_id}")
def get_chunk(
    chunk_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[user_model.User, Depends(get_current_user)],
):
    chunk = db.execute(select(Document).where(
        Document.id == chunk_id, Document.user_id == current_user.id,
    )).scalar_one_or_none()
    if chunk is None:
        raise HTTPException(status_code=404, detail="Source passage not found")
    return {"id": chunk.id, "filename": chunk.filename, "content": chunk.raw_content,
            "chunk_index": chunk.chunk_index, "page_number": chunk.page_number,
            "source_document_id": chunk.source_document_id,
            "element_type": chunk.element_type, "section_title": chunk.section_title,
            "visuals": [{"url": f"/chunks/{chunk.id}/visuals/{index}",
                         "mime_type": asset.get("mime_type", "image/png")}
                        for index, asset in enumerate(chunk.visual_assets or [])]}


@app.get("/chunks/{chunk_id}/visuals/{asset_index}")
def get_chunk_visual(
    chunk_id: int,
    asset_index: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[user_model.User, Depends(get_current_user)],
):
    from fastapi.responses import FileResponse
    from app.services.document_assets import resolve_asset

    chunk = db.execute(select(Document).where(
        Document.id == chunk_id, Document.user_id == current_user.id,
    )).scalar_one_or_none()
    if chunk is None or asset_index < 0 or asset_index >= len(chunk.visual_assets or []):
        raise HTTPException(status_code=404, detail="Visual evidence not found")
    asset = chunk.visual_assets[asset_index]
    try:
        path = resolve_asset(asset["asset_ref"], current_user.id)
    except (FileNotFoundError, KeyError):
        raise HTTPException(status_code=404, detail="Visual evidence not found")
    return FileResponse(path, media_type=asset.get("mime_type", "image/png"),
                        content_disposition_type="inline")


@app.delete("/documents/{document_id}")
def delete_document(
    document_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[user_model.User, Depends(get_current_user)],
):
    chunks = _document_group_rows(document_id, current_user.id, db)
    if chunks[0].source_document_id:
        job = ingestion_queue.get_status(chunks[0].source_document_id, current_user.id)
        if job is None:
            job = get_redis().hgetall(f'job:{chunks[0].source_document_id}')
        if job.get('status') in ('queued', 'processing', 'retrying'):
            raise HTTPException(status_code=409, detail="Wait for document processing to finish before deleting it")
    count = len(chunks)
    if chunks[0].source_document_id:
        ingestion_queue.mark_deleted(db, chunks[0].source_document_id, current_user.id)
    for chunk in chunks:
        db.delete(chunk)
    db.commit()
    if chunks[0].source_document_id:
        from app.services.document_assets import delete_document_assets
        delete_document_assets(current_user.id, chunks[0].source_document_id)
    return {"document_id": document_id, "deleted_chunks": count}


@app.get("/conversations")
def list_conversations(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[user_model.User, Depends(get_current_user)],
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    total = db.query(Conversation).filter(Conversation.user_id == current_user.id).count()
    conversations = db.execute(
        select(Conversation).where(Conversation.user_id == current_user.id)
        .order_by(desc(Conversation.updated_at), desc(Conversation.id)).offset(offset).limit(limit)
    ).scalars().all()
    conversation_ids = [conversation.id for conversation in conversations]
    titles = {}
    if conversation_ids:
        user_messages = db.execute(select(Message.conversation_id, Message.content).where(
            Message.conversation_id.in_(conversation_ids), Message.role == "user",
        ).order_by(Message.created_at, Message.id)).all()
        for conversation_id, content in user_messages:
            if content:
                titles.setdefault(conversation_id, content[:90])
    return {"items": [{"conversation_id": conversation.id, "created_at": conversation.created_at,
                        "updated_at": conversation.updated_at,
                        "title": titles.get(conversation.id, f"Conversation {conversation.id}")}
                       for conversation in conversations],
            "total": total, "limit": limit, "offset": offset}


@app.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[user_model.User, Depends(get_current_user)],
):
    conversation = db.execute(select(Conversation).where(
        Conversation.id == conversation_id, Conversation.user_id == current_user.id,
    )).scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = db.execute(select(Message).where(
        Message.conversation_id == conversation.id,
        Message.role.in_(("user", "assistant")),
    ).order_by(Message.created_at, Message.id)).scalars().all()
    return {"conversation_id": conversation.id, "messages": [{
        "id": message.id, "role": message.role, "content": message.content,
        "created_at": message.created_at,
    } for message in messages if message.content is not None]}


@app.post("/search")
async def semantic_search(
    request: document_schema.SearchRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[user_model.User, Depends(get_current_user)]
):
    similar_docs = await run_blocking(doc_search.generate_relevant_docs, request.query, 5, current_user.id, db)

    return [
        {"id": doc.id, "filename": doc.filename, "content": doc.raw_content,
         "page_number": getattr(doc, "page_number", None),
         "chunk_index": getattr(doc, "chunk_index", None)} for doc in similar_docs
    ]

@app.post("/chat/stream")
def chat_stream(
    request: document_schema.SearchRequest,
    current_user: Annotated[user_model.User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)]
):
    async def stream_events():
        try:
            async for event in run_clinical_agent_stream(
                query=request.query, user_id=current_user.id, db=db,
                llm_provider=llm_provider, conversation_id=request.conversation_id,
            ):
                if event.startswith('data: '):
                    payload = event[6:-2] if event.endswith('\n\n') else event[6:]
                    yield ''.join(f'data: {line}\n' for line in payload.split('\n')) + '\n'
                else:
                    yield event
            yield 'event: complete\ndata: {}\n\n'
        except HTTPException as exc:
            db.rollback()
            yield f'event: error\ndata: {json.dumps({"message": exc.detail})}\n\n'
        except Exception:
            db.rollback()
            yield 'event: error\ndata: {"message": "The answer could not be completed. Please retry."}\n\n'
    return StreamingResponse(stream_events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.post("/chat/agent")
async def chat_agent(
    request: document_schema.SearchRequest,
    current_user: Annotated[user_model.User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)]
):
    result = await run_clinical_agent(
        query=request.query,
        user_id=current_user.id,
        db=db,
        llm_provider=llm_provider,
        conversation_id=request.conversation_id
    )
    return result
