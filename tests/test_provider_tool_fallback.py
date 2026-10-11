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
