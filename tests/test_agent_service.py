from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import agent_service


@pytest.fixture
def conversation_stubs(monkeypatch):
    monkeypatch.setattr(agent_service, "redact_text", lambda text: text)
    monkeypatch.setattr(
        agent_service,
        "get_or_create_conversation",
        lambda db, user_id, conversation_id: SimpleNamespace(id=123),
    )
    monkeypatch.setattr(agent_service, "save_message", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        agent_service,
        "get_conversation_history",
        lambda db, conversation_id, limit: [{"role": "user", "content": "question"}],
    )


def tool_call(arguments):
    return SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(name="search_medical_records", arguments=arguments),
    )


@pytest.mark.asyncio
async def test_direct_response_without_evidence_is_withheld(conversation_stubs):
    provider = SimpleNamespace(
        run_agent=AsyncMock(return_value=SimpleNamespace(tool_calls=None, content="Answer"))
    )
    result = await agent_service.run_clinical_agent("question", 42, MagicMock(), provider)

    assert result == {"response": agent_service.NO_EVIDENCE, "conversation_id": 123, "sources": []}
    provider.run_agent.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_model_cannot_override_user_scope_or_search_limit(monkeypatch, conversation_stubs, stream):
    records = {
        42: [SimpleNamespace(id=10, filename="owned.txt", raw_content="user 42 record")],
        99: [SimpleNamespace(id=20, filename="other.txt", raw_content="user 99 secret")],
    }
    search = MagicMock(side_effect=lambda query, limit, user_id, db: records[user_id][:limit])
    monkeypatch.setitem(agent_service.TOOL_REGISTRY, "search_medical_records", search)
    malicious_call = tool_call('{"query":"headache","user_id":99,"limit":999,"db":"other"}')
    provider = SimpleNamespace(
        run_agent=AsyncMock(side_effect=[
            SimpleNamespace(tool_calls=[malicious_call], content=None),
            SimpleNamespace(tool_calls=None, content="Answer from user 42 record"),
        ])
    )

    async def stream_answer(messages):
        yield "data: Answer from user 42 record\n\n"

    provider.run_agent_stream = stream_answer
    db = MagicMock()

    if stream:
        chunks = [chunk async for chunk in agent_service.run_clinical_agent_stream("question", 42, db, provider)]
        assert "user 99 secret" not in "".join(chunks)
        assert 'event: sources\ndata: [{"document_id": 10, "filename": "owned.txt"}]' in "".join(chunks)
    else:
        result = await agent_service.run_clinical_agent("question", 42, db, provider)
        assert result == {
            "response": "Answer from user 42 record",
            "conversation_id": 123,
            "sources": [{"document_id": 10, "filename": "owned.txt"}],
        }

    search.assert_called_once_with(query="headache", limit=2, user_id=42, db=db)


@pytest.mark.parametrize("arguments", ["not-json", "[]", '{"query": 123}'])
def test_invalid_tool_arguments_use_the_original_query(arguments):
    db = object()
    assert agent_service.search_tool_arguments(arguments, "original", 42, db) == {
        "query": "original", "limit": 2, "user_id": 42, "db": db,
    }


@pytest.mark.asyncio
async def test_chat_redacts_prompt_before_storage_and_provider(monkeypatch, conversation_stubs):
    saved = []
    monkeypatch.setattr(agent_service, "redact_text", lambda text: text.replace("Jane Doe", "<PERSON>"))
    monkeypatch.setattr(
        agent_service,
        "save_message",
        lambda db, conversation_id, role, content, **kwargs: saved.append((role, content)),
    )
    monkeypatch.setattr(
        agent_service,
        "get_conversation_history",
        lambda db, conversation_id, limit: [{"role": "user", "content": saved[0][1]}],
    )
    provider = SimpleNamespace(
        run_agent=AsyncMock(return_value=SimpleNamespace(tool_calls=None, content="unsupported"))
    )

    await agent_service.run_clinical_agent("What happened to Jane Doe?", 42, MagicMock(), provider)

    assert saved[0] == ("user", "What happened to <PERSON>?")
    assert "Jane Doe" not in str(provider.run_agent.await_args.args[0])
