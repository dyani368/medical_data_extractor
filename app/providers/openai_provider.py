from app.providers.base import LLMProvider
from app.providers.tools import tools
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
                                        "You must ONLY answer using the provided context. If the answer is not in the context, you must still return the exact JSON structure, but set the 'summary' to 'Insufficient context', the 'category' to 'General', and the 'confidence' to 0.0."
                                    )
                                },
                                {"role":"user", "content":text}
                            ],
                            response_format={"type": "json_object"}
                    )
        return response.choices[0].message.content
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((openai.RateLimitError, openai.APIError)))
    async def generate_chat_stream(self, context: str,  text: str) -> str:
        response = await client.chat.completions.create(
                            model="openai/gpt-oss-20b",
                            messages=[
                                {
                                    "role":"system", 
                                    "content": (
                                        "You are a clinical AI assistant. Provide a clear, full-sentence answer based on the medical context. "
                                        f"Medical context: {context}\n\n"
                                        "You must ONLY answer using the provided context. If no relevant context is found, reply saying 'I do not have sufficient information to answer this query.'"
                                    )
                                },
                                {"role":"user", "content":text}
                            ],
                            stream=True
                    )
        
        async for chunk in response:
            content = chunk.choices[0].delta.content 
            if content:
                yield f"data: {content}\n\n"
    

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((openai.RateLimitError, openai.APIError)))
    async def run_agent(self, message):

        system_message = {
            "role": "system",
            "content": (
                "You are a clinical AI assistant. Use the available tools to search medical records and retrieve relevant data when answering queries. "
                "Synthesize a clear, accurate, full-sentence answer based on the evidence found in the records. "
                "If no relevant evidence is found, state that you do not have sufficient information."
            )
        }

        full_message = [system_message] + message
                                
        response = await client.chat.completions.create(
                            model="openai/gpt-oss-20b",
                            messages=full_message,
                            tools=tools
                    )
        
        return response.choices[0].message

