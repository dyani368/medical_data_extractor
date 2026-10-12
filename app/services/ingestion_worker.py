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
from app.core.config import settings
from pydantic import ValidationError

async def process_document_job(job_id: str, pages: list[tuple[int | None, str]] | str, filename: str, user_id: int, llm_provider):
    redis = get_redis()
    redis.hset(f"job:{job_id}", mapping={"status": "processing", "progress": "0%"})
    
    db = SessionLocal()
    try:
        redis.hset(f"job:{job_id}", mapping={"progress": "10%", "step": "sanitizing"})
        if isinstance(pages, str):
            pages = [(None, pages)]
        sanitized_pages = [(page_number, sanitize(page_text)) for page_number, page_text in pages]
        
        redis.hset(f"job:{job_id}", mapping={"progress": "20%", "step": "chunking"})
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
        chunks = [(page_number, chunk)
                  for page_number, page_text in sanitized_pages
                  for chunk in text_splitter.split_text(page_text)]
        
        total_chunks = len(chunks)
        results = []
        successful_chunks = 0
        failed_chunks = 0
        redis.hset(f"job:{job_id}", mapping={"total_chunks": total_chunks, "successful_chunks": 0,
                                              "failed_chunks": 0, "extraction_status": "processing"})
        
        for i, (page_number, chunk) in enumerate(chunks):
            progress_pct = int(20 + (i / total_chunks) * 70)
            redis.hset(f"job:{job_id}", mapping={"progress": f"{progress_pct}%", "step": f"processing chunk {i+1}/{total_chunks}"})
            
            new_doc = document_model.Document(
                filename=filename,
                file_url=f"local_text_{uuid.uuid4()}", 
                raw_content=chunk,
                user_id=user_id,
                source_document_id=job_id,
                chunk_index=i,
                page_number=page_number,
            )
            new_doc.embedding = embed_text(chunk)
            db.add(new_doc)
            db.flush()
            
            extraction_status = "succeeded"
            error_type = None
            try:
                raw_json_string = await llm_provider.generate(chunk)
                parsed_data = document_schema.ExtractionResult.model_validate_json(raw_json_string)
            except ValidationError as exc:
                parsed_data = llm_provider.fallback_result()
                extraction_status = "failed"
                error_type = type(exc).__name__
            except Exception as exc:
                parsed_data = llm_provider.fallback_result()
                extraction_status = "failed"
                error_type = type(exc).__name__
                
            new_result = result_model.Result(
                document_id=new_doc.id,
                summary=parsed_data.summary,
                category=parsed_data.category,
                key_entities=parsed_data.key_entities,
                confidence=parsed_data.confidence,
                extraction_status=extraction_status,
                error_type=error_type,
            )
            db.add(new_result)
            db.commit()
            results.append(new_result.id)
            if extraction_status == "succeeded":
                successful_chunks += 1
            else:
                failed_chunks += 1
            redis.hset(f"job:{job_id}", mapping={"successful_chunks": successful_chunks,
                                                  "failed_chunks": failed_chunks})
            
        extraction_status = ("succeeded" if failed_chunks == 0 else
                             "failed" if successful_chunks == 0 else "partial")
        job_status = "completed" if failed_chunks == 0 else "completed_with_errors"
        redis.hset(f"job:{job_id}", mapping={"status": job_status, "progress": "100%",
                                               "result_ids": json.dumps(results),
                                               "successful_chunks": successful_chunks,
                                               "failed_chunks": failed_chunks,
                                               "extraction_status": extraction_status})
        
    except Exception as e:
        redis.hset(f"job:{job_id}", mapping={"status": "failed", "extraction_status": "failed",
                                               "error": type(e).__name__})
    finally:
        redis.expire(f"job:{job_id}", settings.job_retention_seconds)
        db.close()
