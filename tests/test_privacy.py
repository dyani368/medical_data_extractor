from app.core.sanitize import sanitize


def test_redaction_removes_identifiers_but_keeps_clinical_detail():
    text = (
        "Jane Doe, MRN-928174, PT-104, email jane@example.com was prescribed "
        "Lisinopril 10mg on 2026-01-10."
    )

    redacted = sanitize(text)

    for identifier in ("Jane Doe", "MRN-928174", "PT-104", "jane@example.com", "2026-01-10"):
        assert identifier not in redacted
    assert "Lisinopril 10mg" in redacted
