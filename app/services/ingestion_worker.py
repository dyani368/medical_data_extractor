import uuid
import json
import asyncio
from app.core.database import SessionLocal
from app.core.redis_client import get_redis
from app.core.sanitize import sanitize
from langchain_text_splitters import RecursiveCharacterTextSplitter
from app.models import document_model, result_model
from app.schemas import document_schema
from app.core.embeddings import embed_text
from pydantic import ValidationError

async def process_document_job(job_id: str, text: str, filename: str, user_id: int, llm_provider):
    redis = get_redis()
    redis.hset(f"job:{job_id}", mapping={"status": "processing", "progress": "0%"})
    
    db = SessionLocal()
    try:
        redis.hset(f"job:{job_id}", mapping={"progress": "10%", "step": "sanitizing"})
        sanitized_text = sanitize(text)
        
        redis.hset(f"job:{job_id}", mapping={"progress": "20%", "step": "chunking"})
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
        chunks = text_splitter.split_text(sanitized_text)
        
        total_chunks = len(chunks)
        results = []
        
        for i, chunk in enumerate(chunks):
            progress_pct = int(20 + (i / total_chunks) * 70)
            redis.hset(f"job:{job_id}", mapping={"progress": f"{progress_pct}%", "step": f"processing chunk {i+1}/{total_chunks}"})
            
            chunk_filename = f"{filename}_chunk_{i+1}"
            
            new_doc = document_model.Document(
                filename=chunk_filename, 
                file_url=f"local_text_{uuid.uuid4()}", 
                raw_content=chunk,
                user_id=user_id
            )
            new_doc.embedding = embed_text(chunk)
            db.add(new_doc)
            db.flush()
            
            try:
                raw_json_string = await llm_provider.generate(chunk)
                parsed_data = document_schema.ExtractionResult.model_validate_json(raw_json_string)
            except ValidationError as e:
                parsed_data = llm_provider.fallback_result()
            except Exception as e:
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
            results.append(new_result.id)
            
        redis.hset(f"job:{job_id}", mapping={"status": "completed", "progress": "100%", "result_ids": json.dumps(results)})
        
    except Exception as e:
        redis.hset(f"job:{job_id}", mapping={"status": "failed", "error": type(e).__name__})
    finally:
        db.close()
