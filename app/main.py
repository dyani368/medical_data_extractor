from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File, BackgroundTasks, Header, Query
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
from app.core.sanitize import sanitize

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.providers.openai_provider import OpenAIProvider
from app.routers import auth
from app.services.ingestion_worker import process_document_job
from app.services.document_parser import MAX_UPLOAD_BYTES, extract_document_pages
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
    text = sanitize(text)
    new_doc = document_model.Document(
        filename=filename,
        file_url=f"local_text_{uuid.uuid4()}",
        raw_content=text,
        user_id=user_id
    )

    new_doc.embedding = embed_text(text)
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
    background_tasks: BackgroundTasks,
    current_user: Annotated[user_model.User, Depends(get_current_user)],
    file: UploadFile = File(...),
    idempotency_key: str = Header(None)
):
    redis = get_redis()

    if idempotency_key:
        existing_job = redis.get(f"idempotency:{current_user.id}:{idempotency_key}")
        if existing_job:
            return {"status": "accepted", "job_id": existing_job, "document_id": existing_job,
                    "message": "Duplicate request, returning existing job."}

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="File is too large")
    pages = extract_document_pages(content, file.filename, file.content_type)
    safe_filename = sanitize(os.path.basename(file.filename or "document"))

    job_id = str(uuid.uuid4())
    redis.hset(f"job:{job_id}", mapping={"status": "queued", "progress": "0%", "user_id": current_user.id,
                                         "extraction_status": "pending", "total_chunks": 0,
                                         "successful_chunks": 0, "failed_chunks": 0})
    expire_job = getattr(redis, "expire", None)
    if expire_job:
        expire_job(f"job:{job_id}", settings.job_retention_seconds)

    if idempotency_key:
        redis.setex(f"idempotency:{current_user.id}:{idempotency_key}", 86400, job_id)

    background_tasks.add_task(process_document_job, job_id, pages, safe_filename, current_user.id, llm_provider)

    return {"status": "accepted", "job_id": job_id, "document_id": job_id,
            "message": "Document ingestion queued for async processing."}

@app.get("/jobs/{job_id}")
async def get_job_status(
    job_id: str,
    current_user: Annotated[user_model.User, Depends(get_current_user)],
):
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
            "content": chunk.raw_content,
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


@app.delete("/documents/{document_id}")
def delete_document(
    document_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[user_model.User, Depends(get_current_user)],
):
    chunks = _document_group_rows(document_id, current_user.id, db)
    count = len(chunks)
    for chunk in chunks:
        db.delete(chunk)
    db.commit()
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
    return {"items": [{"conversation_id": conversation.id, "created_at": conversation.created_at,
                        "updated_at": conversation.updated_at} for conversation in conversations],
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
    similar_docs = doc_search.generate_relevant_docs(request.query, 5, current_user.id, db)

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
    stream_gen = run_clinical_agent_stream(
        query=request.query,
        user_id=current_user.id,
        db=db,
        llm_provider=llm_provider,
        conversation_id=request.conversation_id
    )
    return StreamingResponse(stream_gen, media_type="text/event-stream")

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
