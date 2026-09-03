import json
from app.providers.base import LLMProvider

class GeminiProvider(LLMProvider):
    async def generate(self, text: str) -> str:
        return json.dumps({
            "summary": "This is a fake Gemini summary",
            "category": "General",
            "key_entities": {},
            "confidence": 0.99
        })