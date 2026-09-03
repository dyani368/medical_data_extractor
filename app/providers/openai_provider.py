from app.providers.base import LLMProvider
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from app.schemas import document_schema
from dotenv import load_dotenv
import openai
from openai import AsyncOpenAI   
import os
load_dotenv()

client = AsyncOpenAI(
    api_key=os.getenv("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)

class OpenAIProvider(LLMProvider):
    def fallback_result() -> document_schema.ExtractionResult:
        return document_schema.ExtractionResult(
            summary = "LLM processing failed after 3 retries",
            category="error",
            key_entities={},
            confidence=0.0
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((openai.RateLimitError, openai.APIError)))
    async def generate(self, text: str) -> str:
        response = await client.chat.completions.create(
                            model="openai/gpt-oss-20b",
                            messages=[
                                {
                                    "role":"system", 
                                    "content": (
                                        "You are a medical data extractor. You must extract information from the user's text and return a raw JSON object. "
                                        "You MUST include ALL 4 of these exact keys in your JSON response: 'summary', 'category', 'key_entities', and 'confidence'. "
                                        "The 'confidence' key must be a float between 0.0 and 1.0 representing your confidence in the extraction. "
                                        "The 'category' key MUST be exactly one of the following: 'Adverse Event', 'Case Report', 'Lab Result', or 'General'."
                                        "Example format: {\"summary\": \"...\", \"category\": \"...\", \"key_entities\": {\"age\": 45}, \"confidence\": 0.95}"
                                    )
                                },
                                {"role":"user", "content":text}
                            ],
                            response_format={"type": "json_object"}
                    )
        return response.choices[0].message.content
