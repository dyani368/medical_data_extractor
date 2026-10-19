from app.services.ingestion_worker import _chunk_elements


def test_chunking_keeps_tables_and_figures_separately_citable():
    elements = [
        {"page_number": 2, "element_type": "text", "section_title": "Results",
         "text": "The patient reported mild dizziness."},
        {"page_number": 2, "element_type": "table", "section_title": "Results",
         "text": "| Measure | Value |\n| --- | --- |\n| Blood pressure | 128/82 |"},
        {"page_number": 2, "element_type": "image", "section_title": "Results",
         "context_text": "Figure 1. Heart rate over time.",
         "asset_ref": "42/example/image.png", "image_mime": "image/png"},
    ]

    chunks = _chunk_elements(elements)
    assert [item["element_type"] for item in chunks] == ["text", "table", "image"]
    assert [item["page_number"] for item in chunks] == [2, 2, 2]
    assert chunks[-1]["visual_assets"] == [{"asset_ref": "42/example/image.png",
                                             "mime_type": "image/png"}]
    assert chunks[-1]["context_text"] == "Figure 1. Heart rate over time."


def test_legacy_page_payloads_remain_readable():
    assert _chunk_elements([(1, "legacy passage")])[0]["text"] == "legacy passage"
