from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine

configuration = {
    "nlp_engine_name": "spacy",
    "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
}
provider = NlpEngineProvider(nlp_configuration=configuration)
nlp_engine = provider.create_engine()

analyzer = AnalyzerEngine(nlp_engine=nlp_engine)
anonymizer = AnonymizerEngine()

mrn_pattern = Pattern(
    name="mrn_pattern", regex=r"\bMRN[0-9]{5}\b", score=0.85
)
mrn_recognizer = PatternRecognizer(
    supported_entity="MEDICAL_RECORD_NUMBER", patterns=[mrn_pattern]
)

trial_subject_pattern = Pattern(name="trial_subj", regex=r"\bSUBJ-[0-9]{4,6}\b", score=0.85)
trial_subject_recognizer = PatternRecognizer(
    supported_entity="SUBJECT_ID", patterns=[trial_subject_pattern]
)
analyzer.registry.add_recognizer(mrn_recognizer, trial_subject_pattern)

def sanitize(text: str):

    results = analyzer.analyze(
        text=text,
        entities=[
            "PERSON",
            "PHONE_NUMBER",
            "EMAIL_ADDRESS",
            "DATE_TIME",
            "SSN",
            "LOCATION",
            "IP_ADDRESS"
            "MEDICAL_RECORD_NUMBER",
            "SUBJECT_ID"
        ],
        language="en",
    )

    return anonymizer.anonymize(text=text,analyzer_results=results).text
  
