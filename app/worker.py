"""Run with python -m app.worker; one claimed job at a time, no Celery/Kafka."""
import asyncio
import logging
import signal
import threading
import time
import uuid
import secrets
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from app.core.config import settings
from app.core.embeddings import embed_text
from app.core.redis_client import get_redis
from app.services import ingestion_queue as queue
from app.services.ingestion_worker import process_document_job
from app.providers.openai_provider import OpenAIProvider

log = logging.getLogger(__name__)

def run_worker(stopping=None):
    if stopping is None:
        stopping = threading.Event()
        for name in ("SIGTERM", "SIGINT"):
            signal.signal(getattr(signal, name), lambda *_: stopping.set())
    provider = OpenAIProvider()
    # Reuse one loop: AsyncOpenAI's connection pool must not cross closed loops.
    loop = asyncio.new_event_loop()
    redis = get_redis()
    next_scan = 0.0
    next_cleanup = 0.0
    while not stopping.is_set():
        try:
            redis.setex("worker:heartbeat", 60, "alive")
            now = time.monotonic()
            if now >= next_cleanup:
                queue.cleanup()
                next_cleanup = now + 3600
            should_scan = now >= next_scan
            if not should_scan:
                # Redis wakes the worker for new jobs. A short blocking wait
                # still lets us refresh the heartbeat and handle shutdown.
                should_scan = bool(redis.blpop(queue.WAKE_KEY, timeout=15))
            if not should_scan:
                continue
            owner = str(uuid.uuid4())
            job = queue.claim(owner)
            if job is None:
                delay = queue.next_due_delay()
                next_scan = time.monotonic() + min(600.0, max(1.0, delay)) if delay is not None else time.monotonic() + 600
                continue
            finished = threading.Event()

            def renew(job_id=job["id"], lease_owner=owner, done=finished):
                while not done.wait(10):
                    try:
                        queue.heartbeat(job_id, lease_owner)
                        redis.setex("worker:heartbeat", 60, "alive")
                    except queue.LeaseLost:
                        return
                    except Exception as exc:
                        log.warning("Heartbeat error: %s", type(exc).__name__)

            heartbeat = threading.Thread(target=renew, daemon=True)
            heartbeat.start()
            log.info("Processing job %s", job["id"])
            try:
                loop.run_until_complete(process_document_job(job["id"], job["pages"], job["filename"],
                                                            job["user_id"], provider, owner))
                log.info("Finished job %s", job["id"])
            except queue.LeaseLost:
                log.warning("Lease lost for %s; another worker may recover it", job["id"])
            except Exception as exc:
                log.warning("Job %s encountered %s", job["id"], type(exc).__name__)
                try:
                    queue.retry(job["id"], owner, exc)
                except queue.LeaseLost:
                    pass
            finally:
                finished.set()
                heartbeat.join(timeout=2)
                # Drain any queued work before sleeping again.
                next_scan = 0.0
        except Exception as exc:
            log.warning("Queue unavailable: %s", type(exc).__name__)
            stopping.wait(3)
            next_scan = 0.0
    loop.close()


embedding_app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


class EmbeddingRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


@embedding_app.post("/embed")
def embedding(request: EmbeddingRequest, x_worker_key: str = Header("")):
    if not secrets.compare_digest(x_worker_key, settings.secret_key):
        raise HTTPException(403, "Forbidden")
    return {"embedding": embed_text(request.text)}


if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    stopping = threading.Event()
    thread = threading.Thread(target=run_worker, args=(stopping,), daemon=True)
    thread.start()
    try:
        # Internal Docker network only: never published to a host port.
        uvicorn.run(embedding_app, host="0.0.0.0", port=8001, log_level="warning")
    finally:
        stopping.set()
        thread.join(timeout=80)
