import pytest
import json
from unittest.mock import patch
from app.providers.gemini_provider import GeminiProvider
from app.providers.openai_provider import OpenAIProvider

@pytest.mark.asyncio
async def test_gemini_provider_mocking():
    mock_provider = GeminiProvider()

    raw_json_string = await mock_provider.generate("Ssome medical text")
    result_dict = json.loads(raw_json_string)

    assert result_dict["summary"] == "This is a fake Gemini summary"
    assert result_dict["category"] == "General"
    assert result_dict["confidence"] == 0.99

@pytest.mark.asyncio
@patch('app.providers.openai_provider.OpenAIProvider.generate')
async def test_openai_provider_with_patching(mock_generate):
    fake_response = json.dumps({
        "summary": "Mocked OpenAI summary",
        "category": "Lab Result",
        "key_entities": {},
        "confidence": 0.85
    })
    mock_generate.return_value = fake_response

    provider = OpenAIProvider()

    raw_json_string = await provider.generate("Patient has weird lab results")
    result_dict = json.loads(raw_json_string)
    assert result_dict["summary"] == "Mocked OpenAI summary"

    mock_generate.assert_called_once_with("Patient has weird lab results")