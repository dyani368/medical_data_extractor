from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import openai
import pytest

from app.providers import openai_provider


@pytest.mark.asyncio
async def test_malformed_tool_call_falls_back_to_server_search(monkeypatch):
    error = openai.BadRequestError(
        "Tool generation failed", response=httpx.Response(400, request=httpx.Request("POST", "https://example.test")),
        body={"code": "tool_use_failed", "failed_generation": "untrusted invalid call"},
    )
    create = AsyncMock(side_effect=error)
    monkeypatch.setattr(openai_provider, "client", SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    result = await openai_provider.OpenAIProvider().run_agent(
        [{"role": "user", "content": "What adverse event was reported?"}], require_tool=True
    )
    assert result.tool_calls[0].function.name == "search_medical_records"
    assert "What adverse event was reported?" in result.tool_calls[0].function.arguments
    assert "untrusted" not in result.tool_calls[0].function.arguments
    create.assert_awaited_once()


@pytest.mark.asyncio
async def test_final_answer_does_not_offer_tools_to_model(monkeypatch):
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Insufficient evidence", tool_calls=None))])
    create = AsyncMock(return_value=response)
    monkeypatch.setattr(openai_provider, "client", SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    result = await openai_provider.OpenAIProvider().run_agent(
        [{"role": "user", "content": "What was the amount?"}], require_tool=False
    )
    assert result.content == "Insufficient evidence"
    kwargs = create.await_args.kwargs
    assert "tools" not in kwargs
    assert "tool_choice" not in kwargs


@pytest.mark.asyncio
async def test_final_answer_flattens_prior_tool_transcript_but_keeps_evidence(monkeypatch):
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Answer [doc:7]", tool_calls=None))])
    create = AsyncMock(return_value=response)
    monkeypatch.setattr(openai_provider, "client", SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    await openai_provider.OpenAIProvider().run_agent([
        {"role": "user", "content": "What was reported?"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1"}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "[doc:7] Reported finding."},
    ], require_tool=False)
    sent = create.await_args.kwargs["messages"]
    assert all(item["role"] != "tool" and "tool_calls" not in item for item in sent)
    assert any("[doc:7] Reported finding." in item["content"] for item in sent)
