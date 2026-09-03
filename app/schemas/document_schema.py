from pydantic import BaseModel, Field, ConfigDict  
from datetime import datetime

class DocumentRequest(BaseModel):
    text: str

from typing import Literal

class ExtractionResult(BaseModel):
    summary: str
    category: Literal['Adverse Event', 'Case Report', 'Lab Result', 'General']
    key_entities: dict
    confidence: float

class ResultResponse(ExtractionResult):
    id: int
    document_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class SearchRequest(BaseModel):
    query: str


    