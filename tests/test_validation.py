import pytest
from pydantic import ValidationError
from app.schemas.document_schema import ExtractionResult

def test_valid_extraction_passes():
    valid_data = {
        "summary": "Patient has a headache.",
        "category": "Adverse Event",
        "key_entities": {"symptom": "headache"},
        "confidence": 0.95
    }
    result = ExtractionResult(**valid_data)
    assert result.confidence == 0.95

def test_missing_summary_fails():
    bad_data = {
        "category": "Adverse Event",
        "key_entities": {},
        "confidence": 0.95
    }
    with pytest.raises(ValidationError):
        ExtractionResult(**bad_data)

def test_invalid_category_fails():
    bad_data = {
        "summary": "Patient is fine.",
        "category": "Not A Real Category",
        "key_entities": {},
        "confidence": 0.95
    }
    with pytest.raises(ValidationError):
        ExtractionResult(**bad_data)

def test_invalid_confidence_type():
    bad_data = {
        "summary": "Patient has a headache.",
        "category": "Adverse Event",
        "key_entities": {},
        "confidence": "high" 
    }
    with pytest.raises(ValidationError):
        ExtractionResult(**bad_data)

def test_empty_entities_accepted():
    valid_data = {
        "summary": "Patient is fine.",
        "category": "General",
        "key_entities": {},
        "confidence": 0.99
    }
    result = ExtractionResult(**valid_data)
    assert result.key_entities == {}
