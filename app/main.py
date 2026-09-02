from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from pydantic import ValidationError
import json

from app.routers import auth
from app.schemas import document_schema, user_schema
from app.models import document_model, result_model, user_model
from app.core.database import engine, Base, get_db
from app.core.security import get_current_user, create_access_token, verify_password, get_password_hash
from fastapi.security import OAuth2PasswordRequestForm
from datetime import timedelta
from app.core.config import settings

import uuid
import os
import asyncio
from openai import AsyncOpenAI   
from dotenv import load_dotenv

app = FastAPI()
app.include_router(auth.router)
Base.metadata.create_all(bind=engine)
load_dotenv()

client = AsyncOpenAI(
    api_key=os.getenv("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)

async def run_extraction_pipeline(text: str, filename: str, db: Session, user_id: int):
    try:
        new_doc = document_model.Document(
            filename=filename, 
            file_url=f"local_text_{uuid.uuid4()}", 
            raw_content=text,
            user_id=user_id
        )
        db.add(new_doc)
        db.flush()

        response = await client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[
                {
                    "role":"system", 
                    "content":"You are a medical data extractor. You must extract information and return a JSON object exactly matching this schema: {'summary': 'string', 'category': 'string', 'key_entities': 'dictionary', 'confidence': 'float'}"
                },
                {"role":"user", "content":text}
            ],
            response_format={"type": "json_object"}
        )
        
        raw_json_string = response.choices[0].message.content
        parsed_data = document_schema.ExtractionResult.model_validate_json(raw_json_string)

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

    except ValidationError as e:
        raise HTTPException(status_code=422, detail=f"LLM returned invalid JSON structure: {e.errors()}")
    except Exception as e:
        print(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/process", response_model=document_schema.ResultResponse)
async def process_document(request: document_schema.DocumentRequest, db: Session=Depends(get_db), current_user: user_model.User = Depends(get_current_user)):
    return await run_extraction_pipeline(request.text, "api_upload.txt", db, current_user.id)

@app.post("/upload", response_model=document_schema.ResultResponse)
async def upload_document(file: UploadFile = File(...), db: Session=Depends(get_db), current_user: user_model.User = Depends(get_current_user)):
    content = await file.read()
    text = content.decode("utf-8")
    return await run_extraction_pipeline(text, file.filename, db, current_user.id)
    
