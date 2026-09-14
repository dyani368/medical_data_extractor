import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.agent_service import run_clinical_agent, TOOL_REGISTRY

@pytest.mark.asyncio
async def test_run_clinical_agent_direct_response():
    mock_provider = MagicMock()
    mock_response = MagicMock()
    mock_response.tool_calls = None
    mock_response.content = "Clinical answer without tools."
    mock_provider.run_agent = AsyncMock(return_value=mock_response)

    mock_db = MagicMock()
    answer = await run_clinical_agent(
        query="What is normal blood pressure?",
        user_id=1,
        db=mock_db,
        llm_provider=mock_provider
    )

    assert answer == "Clinical answer without tools."
    mock_provider.run_agent.assert_called_once()

@pytest.mark.asyncio
async def test_run_clinical_agent_with_tool_call():
    mock_provider = MagicMock()

    mock_tool_call = MagicMock()
    mock_tool_call.id = "call_abc123"
    mock_tool_call.function.name = "search_medical_records"
    mock_tool_call.function.arguments = '{"query": "headache"}'

    step1_response = MagicMock()
    step1_response.tool_calls = [mock_tool_call]
    step1_response.content = None

    step2_response = MagicMock()
    step2_response.tool_calls = None
    step2_response.content = "Patient had headaches treated with acetaminophen."

    mock_provider.run_agent = AsyncMock(side_effect=[step1_response, step2_response])

    mock_doc = MagicMock()
    mock_doc.raw_content = "Patient reported severe headaches on 2026-01-10."
    
    mock_handler = MagicMock(return_value=[mock_doc])
    original_handler = TOOL_REGISTRY.get("search_medical_records")
    TOOL_REGISTRY["search_medical_records"] = mock_handler

    try:
        mock_db = MagicMock()
        answer = await run_clinical_agent(
            query="Tell me about headaches",
            user_id=42,
            db=mock_db,
            llm_provider=mock_provider
        )

        assert answer == "Patient had headaches treated with acetaminophen."
        assert mock_provider.run_agent.call_count == 2
        mock_handler.assert_called_once_with(query="headache", limit=2, user_id=42, db=mock_db)
    finally:
        if original_handler:
            TOOL_REGISTRY["search_medical_records"] = original_handler
