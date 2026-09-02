from pydantic import BaseModel, Field, ConfigDict  
from datetime import datetime

class DocumentRequest(BaseModel):
    text: str

class ExtractionResult(BaseModel):
    summary: str
    category: str
    key_entities: dict
    confidence: float

class ResultResponse(ExtractionResult):
    id: int
    document_id: int
    created_at: datetime

    class Config:
        from_attributes = True


    