from types import SimpleNamespace
from unittest.mock import MagicMock
import asyncio
import threading

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import main
from app.core.database import get_db
from app.core.security import get_current_user


def test_ingestion_cpu_work_runs_outside_api_event_loop(monkeypatch):
    from app.services import ingestion_worker as worker
    event_loop_thread = threading.get_ident()
    cpu_threads = []

    def sanitize(text):
        cpu_threads.append(threading.get_ident())
        return text

    def embed(text):
        cpu_threads.append(threading.get_ident())
        return [0.0] * 384

    async def generate(text):
        return '{"summary":"sample","category":"General","key_entities":{},"confidence":0.8}'

    monkeypatch.setattr(worker, "sanitize", sanitize)
    monkeypatch.setattr(worker, "embed_text", embed)
    monkeypatch.setattr(worker, "SessionLocal", MagicMock())
    monkeypatch.setattr(worker, "get_redis", MagicMock())
    asyncio.run(worker.process_document_job("test-job", [(1, "sample")], "sample.pdf", 42,
                                            SimpleNamespace(generate=generate)))
    assert len(cpu_threads) == 2
    assert all(thread != event_loop_thread for thread in cpu_threads)


def test_source_passage_lookup_always_scopes_to_authenticated_user():
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = None
    with pytest.raises(HTTPException) as error:
        main.get_chunk(999, db, SimpleNamespace(id=42))
    assert error.value.status_code == 404
    parameters = db.execute.call_args.args[0].compile().params
    assert parameters["id_1"] == 999
    assert parameters["user_id_1"] == 42


def test_stream_preserves_multiline_tokens_and_reports_completion(monkeypatch):
    monkeypatch.setattr(main, "initialize_database", lambda: None)

    async def stream(**kwargs):
        yield 'event: conversation\ndata: {"conversation_id": 7}\n\n'
        yield 'data: first\nsecond\n\n'

    monkeypatch.setattr(main, "run_clinical_agent_stream", stream)
    main.app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=42)
    main.app.dependency_overrides[get_db] = lambda: MagicMock()
    try:
        with TestClient(main.app) as client:
            response = client.post('/chat/stream', json={"query": "question"})
        assert response.status_code == 200
        assert 'event: conversation\ndata: {"conversation_id": 7}' in response.text
        assert 'data: first\ndata: second\n\n' in response.text
        assert 'event: complete\ndata: {}' in response.text
    finally:
        main.app.dependency_overrides.clear()


def test_stream_provider_errors_are_explicit_events(monkeypatch):
    monkeypatch.setattr(main, "initialize_database", lambda: None)

    async def broken_stream(**kwargs):
        yield 'event: conversation\ndata: {"conversation_id": 7}\n\n'
        raise RuntimeError("private provider details")

    monkeypatch.setattr(main, "run_clinical_agent_stream", broken_stream)
    main.app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=42)
    main.app.dependency_overrides[get_db] = lambda: MagicMock()
    try:
        with TestClient(main.app) as client:
            response = client.post('/chat/stream', json={"query": "question"})
        assert 'event: error' in response.text
        assert 'private provider details' not in response.text
        assert 'event: complete' not in response.text
    finally:
        main.app.dependency_overrides.clear()
