from fastapi import FastAPI, Depends, HTTPException,status, UploadFile, File
from sqlalchemy.orm import Session
from pydantic import ValidationError
import json

from app.models import document_model, result_model, user_model
from app.schemas import document_schema, user_schema
from app.routers import auth
from app.core.database import engine, Base, get_db
from app.core.security import get_current_user, create_access_token, verify_password, get_password_hash
from fastapi.security import OAuth2PasswordRequestForm
from datetime import timedelta
from app.core.config import settings

from app.providers.openai_provider import OpenAIProvider

import uuid
import os
import asyncio

from dotenv import load_dotenv

app = FastAPI()
app.include_router(auth.router)
Base.metadata.create_all(bind=engine)
load_dotenv()

llm_provider = OpenAIProvider()

async def run_extraction_pipeline(text: str, filename: str, db: Session, user_id: int):
    new_doc = document_model.Document(
        filename=filename, 
        file_url=f"local_text_{uuid.uuid4()}", 
        raw_content=text,
        user_id=user_id
    )
    db.add(new_doc)
    db.flush()
    
    try:
        raw_json_string = await llm_provider.generate(text)
        parsed_data = document_schema.ExtractionResult.model_validate_json(raw_json_string)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=f"LLM returned invalid JSON structure: {e.errors()}")
    except Exception as e:
        print(f"LLM failed after 3 retries: {e}")
        parsed_data = fallback_result()

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
async def process_document(request: document_schema.DocumentRequest, db: Session=Depends(get_db), current_user: user_model.User = Depends(get_current_user)):
    return await run_extraction_pipeline(request.text, "api_upload.txt", db, current_user.id)

@app.post("/upload", response_model=document_schema.ResultResponse)
async def upload_document(file: UploadFile = File(...), db: Session=Depends(get_db), current_user: user_model.User = Depends(get_current_user)):
    if file.content_type != "text/plain":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only text files are allowed")

    content = await file.read()
    text = content.decode("utf-8")
    return await run_extraction_pipeline(text, file.filename, db, current_user.id)
    
