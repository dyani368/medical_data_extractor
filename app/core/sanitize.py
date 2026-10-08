import re
from functools import lru_cache

from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine

configuration = {
    "nlp_engine_name": "spacy",
    "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
}
mrn_pattern = Pattern(
    name="mrn_pattern", regex=r"\bMRN[- ]?[0-9]{5,10}\b", score=1.0
)
mrn_recognizer = PatternRecognizer(
    supported_entity="MEDICAL_RECORD_NUMBER", patterns=[mrn_pattern]
)

trial_subject_pattern = Pattern(name="trial_subj", regex=r"\bSUBJ-[0-9]{4,6}\b", score=1.0)
trial_subject_recognizer = PatternRecognizer(
    supported_entity="SUBJECT_ID", patterns=[trial_subject_pattern]
)
patient_id_pattern = Pattern(name="patient_id", regex=r"\bPT-[0-9]{3,8}\b", score=1.0)
patient_id_recognizer = PatternRecognizer(
    supported_entity="PATIENT_ID", patterns=[patient_id_pattern]
)
@lru_cache(maxsize=1)
def get_analyzer():
    provider = NlpEngineProvider(nlp_configuration=configuration)
    analyzer = AnalyzerEngine(nlp_engine=provider.create_engine())
    analyzer.registry.add_recognizer(mrn_recognizer)
    analyzer.registry.add_recognizer(trial_subject_recognizer)
    analyzer.registry.add_recognizer(patient_id_recognizer)
    return analyzer

def sanitize(text: str):

    results = get_analyzer().analyze(
        text=text,
        entities=[
            "PERSON",
            "PHONE_NUMBER",
            "EMAIL_ADDRESS",
            "SSN",
            "LOCATION",
            "IP_ADDRESS",
            "MEDICAL_RECORD_NUMBER",
            "SUBJECT_ID",
            "PATIENT_ID",
        ],
        language="en",
    )

    redacted = AnonymizerEngine().anonymize(text=text, analyzer_results=results).text
    redacted = re.sub(r"\b(?:19|20)\d{2}[-/]\d{1,2}[-/]\d{1,2}\b", "<DATE>", redacted)
    redacted = re.sub(r"\b\d{1,2}[-/]\d{1,2}[-/](?:19|20)\d{2}\b", "<DATE>", redacted)
    return redacted
  
