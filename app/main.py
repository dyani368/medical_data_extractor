from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException,status, UploadFile, File, Request, BackgroundTasks, Header
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import select, text
from typing import Annotated
from pydantic import ValidationError

from fastapi.security import OAuth2PasswordRequestForm
from datetime import timedelta

from app.models import document_model, result_model, user_model, conversation_model, audit_model
from app.schemas import document_schema, user_schema
from app.services import doc_search
from app.services.agent_service import run_clinical_agent, run_clinical_agent_stream

from app.core.database import engine, Base, get_db
from app.core.security import get_current_user, create_access_token, verify_password, get_password_hash
from app.core.config import settings
from app.core.embeddings import embed_text
from app.core.sanitize import sanitize

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.providers.openai_provider import OpenAIProvider
from app.routers import auth
from app.services.ingestion_worker import process_document_job
from app.services.document_parser import MAX_UPLOAD_BYTES, extract_document_text
from app.core.redis_client import get_redis

import uuid
import os
import asyncio
import json

from dotenv import load_dotenv

def initialize_database():
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind=engine)


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
            return {"status": "accepted", "job_id": existing_job, "message": "Duplicate request, returning existing job."}

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="File is too large")
    text = extract_document_text(content, file.filename, file.content_type)
    safe_filename = sanitize(os.path.basename(file.filename or "document"))

    job_id = str(uuid.uuid4())
    redis.hset(f"job:{job_id}", mapping={"status": "queued", "progress": "0%", "user_id": current_user.id})

    if idempotency_key:
        redis.setex(f"idempotency:{current_user.id}:{idempotency_key}", 86400, job_id)

    background_tasks.add_task(process_document_job, job_id, text, safe_filename, current_user.id, llm_provider)

    return {"status": "accepted", "job_id": job_id, "message": "Document ingestion queued for async processing."}

@app.get("/jobs/{job_id}")
async def get_job_status(
    job_id: str,
    current_user: Annotated[user_model.User, Depends(get_current_user)],
):
    redis = get_redis()
    job_data = redis.hgetall(f"job:{job_id}")
    if not job_data or job_data.get("user_id") != str(current_user.id):
        raise HTTPException(status_code=404, detail="Job not found")
    return {key: value for key, value in job_data.items() if key != "user_id"}


@app.post("/search")
async def semantic_search(
    request: document_schema.SearchRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[user_model.User, Depends(get_current_user)]
):
    similar_docs = doc_search.generate_relevant_docs(request.query, 1,current_user.id, db, threshold = 0.45)

    return [
        {"id": doc.id, "filename": doc.filename, "content": doc.raw_content} for doc in similar_docs
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
