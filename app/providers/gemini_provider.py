from app.providers.base import LLMProvider

class OpenAIProvider(LLMProvider):
        return json.dumps({
            "summary": "This is a fake Gemini summary",
            "category": "General",
            "key_entities": {},
            "confidence": 0.99
        })