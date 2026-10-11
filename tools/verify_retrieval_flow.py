"""Live, read-only demo verification. Chats/audits stay in memory; Neon is never written.

Usage: python tools/verify_retrieval_flow.py --user-id YOUR_USER_ID [--llm]
The --llm option sends redacted retrieved passages to the configured LLM provider.
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from app.core.config import settings
from app.services import doc_search, agent_service


class ReadOnlyDB:
    def __init__(self, session):
        self.session = session

    def execute(self, statement):
        return self.session.execute(statement)

    def add(self, item):
        pass  # Audit objects remain local to this verification.

    def commit(self):
        pass

    def rollback(self):
        pass


async def verify(user_id, use_llm):
    engine = create_engine(settings.database_url, connect_args={"connect_timeout": 10})
    with Session(engine) as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        db = ReadOnlyDB(session)
        for query, expected in [
            ("What adverse event was reported?", "nausea"),
            ("Did the patient report chest pain or shortness of breath?", "denies chest pain"),
        ]:
            docs = doc_search.generate_relevant_docs(query, 5, user_id, db)
            assert all(doc.user_id == user_id for doc in docs)
            assert any(expected in doc.raw_content.lower() for doc in docs), query
            print("PASS retrieval:", query, "document IDs:", [doc.id for doc in docs], flush=True)
        if not use_llm:
            return
        from app.providers import openai_provider
        openai_provider.client = openai_provider.client.with_options(timeout=30, max_retries=0)
        provider = openai_provider.OpenAIProvider()
        messages = []

        def save(db, conversation_id, role, content, tool_calls=None, tool_call_id=None):
            message = {"role": role, "content": content}
            if tool_calls:
                message["tool_calls"] = [call.model_dump(exclude_none=True) for call in tool_calls]
            if tool_call_id:
                message["tool_call_id"] = tool_call_id
            messages.append(message)

        with patch.object(agent_service, "get_or_create_conversation", return_value=SimpleNamespace(id=1)), \
             patch.object(agent_service, "get_conversation_history", side_effect=lambda *args, **kwargs: list(messages)), \
             patch.object(agent_service, "save_message", side_effect=save):
            for query, expected in [
                ("What blood pressure and symptom were recorded in the cardiovascular follow-up?", ("160/95",)),
                ("Did the patient report chest pain or shortness of breath?", ("den", "did not", "no chest")),
                ("What adverse event was reported?", ("nausea",)),
            ]:
                result = await agent_service.run_clinical_agent(query, user_id, db, provider, conversation_id=1)
                print("LIVE answer:", result, flush=True)
                assert any(word in result["response"].lower() for word in expected) and result["sources"], query
            result = await agent_service.run_clinical_agent(
                "What was the patient's hemoglobin A1c lab value?", user_id, db, provider, conversation_id=1
            )
            print("LIVE unsupported question:", result, flush=True)
            assert any(word in result["response"].lower() for word in (
                "insufficient", "not", "no ", "don't have sufficient", "don’t have sufficient"
                , "don't have enough", "don’t have enough"
            )), result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--llm", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(verify(args.user_id, args.llm))
    except Exception as error:
        print("Verification failed:", type(error).__name__)
        cause = error.last_attempt.exception() if hasattr(error, "last_attempt") else error
        print("Cause:", type(cause).__name__, "HTTP status:", getattr(cause, "status_code", None))
        if isinstance(getattr(cause, "body", None), dict):
            detail = cause.body.get("error", cause.body)
            print("Provider error code:", detail.get("code") if isinstance(detail, dict) else None)
        sys.exit(1)
