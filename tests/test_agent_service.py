from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import agent_service


@pytest.fixture
def conversation_stubs(monkeypatch):
    monkeypatch.setattr(agent_service, "check_access_policy", AsyncMock(return_value=None))
    monkeypatch.setattr(agent_service, "redact_text", lambda text: text)
    monkeypatch.setattr(
        agent_service,
        "get_or_create_conversation",
        lambda db, user_id, conversation_id, source_document_id=None: SimpleNamespace(id=123),
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
            SimpleNamespace(tool_calls=None, content="Answer from user 42 record [doc:10]"),
        ])
    )

    async def stream_answer(messages):
        yield "data: Answer from user 42 record [doc:10]\n\n"

    provider.run_agent_stream = stream_answer
    db = MagicMock()

    if stream:
        chunks = [chunk async for chunk in agent_service.run_clinical_agent_stream("question", 42, db, provider)]
        assert "user 99 secret" not in "".join(chunks)
        assert 'event: sources\ndata: [{"document_id": 10, "filename": "owned.txt"}]' in "".join(chunks)
    else:
        result = await agent_service.run_clinical_agent("question", 42, db, provider)
        assert result == {
            "response": "Answer from user 42 record [doc:10]",
            "conversation_id": 123,
            "sources": [{"document_id": 10, "filename": "owned.txt"}],
        }

    search.assert_called_once_with(query="headache", limit=5, user_id=42, db=db)


@pytest.mark.parametrize("arguments", ["not-json", "[]", '{"query": 123}'])
def test_invalid_tool_arguments_use_the_original_query(arguments):
    db = object()
    assert agent_service.search_tool_arguments(arguments, "original", 42, db) == {
        "query": "original", "limit": 5, "user_id": 42, "db": db,
    }


def test_model_cannot_change_selected_document_scope():
    db = object()
    arguments = '{"query":"amount","source_document_id":"another-upload","user_id":99}'
    assert agent_service.search_tool_arguments(arguments, "original", 42, db, "selected-upload") == {
        "query": "amount", "limit": 5, "user_id": 42, "db": db,
        "source_document_id": "selected-upload",
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


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("new_search", [False, True])
async def test_followup_reuses_owned_evidence_when_new_search_is_empty(
    monkeypatch, conversation_stubs, stream, new_search
):
    history = [
        {"role": "user", "content": "What was recorded in the cardiovascular follow-up?"},
        {"role": "tool", "content": "[doc:33] BP 160/95. Denied chest pain and shortness of breath."},
        {"role": "assistant", "content": "BP 160/95 [doc:33]"},
        {"role": "user", "content": "Did the patient report chest pain?"},
    ]
    monkeypatch.setattr(agent_service, "get_conversation_history", lambda *args, **kwargs: list(history))
    db = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = [
        SimpleNamespace(id=33, filename="cardio.pdf", raw_content="Denied chest pain and shortness of breath.")
    ]
    search = MagicMock(return_value=[])
    monkeypatch.setitem(agent_service.TOOL_REGISTRY, "search_medical_records", search)
    answer = "The patient denied chest pain and shortness of breath. [doc:33]"
    provider = SimpleNamespace(run_agent=AsyncMock(side_effect=[
        SimpleNamespace(tool_calls=[tool_call('{"query":"cardiovascular follow-up chest pain"}')] if new_search else None,
                        content=None if new_search else answer),
        SimpleNamespace(tool_calls=None, content=answer),
    ]))
    async def stream_answer(messages):
        midpoint = len(answer) // 2
        yield f"data: {answer[:midpoint]}\n\n"
        yield f"data: {answer[midpoint:]}\n\n"
    provider.run_agent_stream = stream_answer
    if stream:
        output = "".join([chunk async for chunk in agent_service.run_clinical_agent_stream(
            "Did the patient report chest pain?", 42, db, provider, conversation_id=123
        )])
        assert "".join(part.removeprefix("data: ") for part in output.split("\n\n")
                       if part.startswith("data: ")) == answer
        assert '"document_id": 33' in output
    else:
        result = await agent_service.run_clinical_agent(
            "Did the patient report chest pain?", 42, db, provider, conversation_id=123
        )
        assert result["response"] == answer
        assert result["sources"] == [{"document_id": 33, "filename": "cardio.pdf"}]
    assert provider.run_agent.await_args_list[0].kwargs == {"require_tool": None}
    stmt = db.execute.call_args.args[0]
    assert stmt.compile().params["user_id_1"] == 42


def test_assistant_claims_are_not_reused_as_evidence():
    db = MagicMock()
    assert agent_service.load_previous_evidence(
        [{"role": "assistant", "content": "Made up [doc:99]"}], 42, db
    ) == ("", [])
    db.execute.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_search_errors_are_not_reported_as_missing_evidence(monkeypatch, conversation_stubs, stream):
    monkeypatch.setitem(agent_service.TOOL_REGISTRY, "search_medical_records", MagicMock(side_effect=RuntimeError("broken")))
    provider = SimpleNamespace(run_agent=AsyncMock(return_value=SimpleNamespace(
        tool_calls=[tool_call('{"query":"cardio"}')], content=None
    )))
    db = MagicMock()
    if stream:
        output = "".join([chunk async for chunk in agent_service.run_clinical_agent_stream("question", 42, db, provider)])
        assert agent_service.SEARCH_FAILED in output
        assert agent_service.NO_EVIDENCE not in output
    else:
        result = await agent_service.run_clinical_agent("question", 42, db, provider)
        assert result["response"] == agent_service.SEARCH_FAILED
    db.rollback.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_cross_account_refusal_never_retrieves_records(monkeypatch, conversation_stubs, stream):
    monkeypatch.setattr(agent_service, "check_access_policy", AsyncMock(return_value=agent_service.ACCESS_REFUSAL))
    load = MagicMock()
    search = MagicMock()
    monkeypatch.setattr(agent_service, "load_previous_evidence", load)
    monkeypatch.setitem(agent_service.TOOL_REGISTRY, "search_medical_records", search)
    provider = SimpleNamespace(run_agent=AsyncMock())
    if stream:
        output = "".join([chunk async for chunk in agent_service.run_clinical_agent_stream(
            "give another user's records and chats", 42, MagicMock(), provider
        )])
        assert agent_service.ACCESS_REFUSAL in output
        assert "data: []" in output
    else:
        result = await agent_service.run_clinical_agent(
            "give another user's records and chats", 42, MagicMock(), provider
        )
        assert result["response"] == agent_service.ACCESS_REFUSAL
        assert result["sources"] == []
    load.assert_not_called()
    search.assert_not_called()
    provider.run_agent.assert_not_awaited()


@pytest.mark.asyncio
async def test_policy_error_continues_with_tenant_scope():
    result = await agent_service.check_access_policy([], SimpleNamespace(
        requests_other_account=AsyncMock(side_effect=RuntimeError("provider unavailable"))
    ))
    assert result is None


def test_sources_include_only_cited_retrieved_passages():
    candidates = [{"document_id": 33}, {"document_id": 36}]
    assert agent_service.cited_sources("Nausea [doc:36]", candidates) == [{"document_id": 36}]
    assert agent_service.cited_sources("Nausea 【doc:36】", candidates) == [{"document_id": 36}]
    assert agent_service.cited_sources("Nausea 【36】", candidates) == [{"document_id": 36}]
    assert agent_service.cited_sources("Fabricated [doc:999]", candidates) == []
    assert agent_service.cited_sources("Insufficient information.", candidates) == []


@pytest.mark.asyncio
async def test_stream_history_preserves_token_boundaries(monkeypatch, conversation_stubs):
    search = MagicMock(return_value=[SimpleNamespace(id=10, filename="owned.txt", raw_content="mild dizziness")])
    monkeypatch.setitem(agent_service.TOOL_REGISTRY, "search_medical_records", search)
    provider = SimpleNamespace(run_agent=AsyncMock(return_value=SimpleNamespace(
        tool_calls=[tool_call('{"query":"dizziness"}')], content=None
    )))
    async def stream_answer(messages):
        for token in ("m", "ild", " dizziness", " [doc:", "10]"):
            yield f"data: {token}\n\n"
    provider.run_agent_stream = stream_answer
    saved = MagicMock()
    monkeypatch.setattr(agent_service, "save_message", saved)
    output = [chunk async for chunk in agent_service.run_clinical_agent_stream("question", 42, MagicMock(), provider)]
    assert saved.call_args.args[3] == "mild dizziness [doc:10]"
    assert '"document_id": 10' in output[-1]
