from app.services.ingestion_worker import _chunk_elements


def test_chunking_keeps_tables_and_figures_separately_citable():
    elements = [
        {"page_number": 2, "element_type": "text", "section_title": "Results",
         "text": "The patient reported mild dizziness."},
        {"page_number": 2, "element_type": "table", "section_title": "Results",
         "text": "| Measure | Value |\n| --- | --- |\n| Blood pressure | 128/82 |",
         "bbox": [50, 125, 350, 205]},
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
    assert chunks[1]["bbox"] == [50, 125, 350, 205]


def test_legacy_page_payloads_remain_readable():
    assert _chunk_elements([(1, "legacy passage")])[0]["text"] == "legacy passage"


def test_adjacent_pdf_text_keeps_table_header_and_value_together():
    elements = [
        {"page_number": 1, "element_type": "text", "text": "Net gain or loss (-)"},
        {"page_number": 1, "element_type": "text", "text": "Total Short-term"},
        {"page_number": 1, "element_type": "text", "text": "0.64"},
        {"page_number": 2, "element_type": "text", "text": "Different page"},
    ]
    chunks = _chunk_elements(elements)
    assert len(chunks) == 2
    assert chunks[0]["page_number"] == 1
    assert "Net gain or loss (-)\nTotal Short-term\n0.64" == chunks[0]["text"]
    assert chunks[1]["page_number"] == 2
