import fitz
import pytest

from fastapi import HTTPException

from app.services.document_parser import MAX_PDF_PAGES, extract_document_elements


def make_mixed_pdf():
    vector = fitz.open()
    vector_page = vector.new_page(width=140, height=100)
    vector_page.draw_rect(fitz.Rect(5, 5, 135, 95), color=(0.1, 0.3, 0.2), fill=(0.8, 0.9, 0.8))
    vector_page.insert_text((12, 42), "Heart rate trend", fontsize=10)
    image = vector_page.get_pixmap().tobytes("png")

    pdf = fitz.open()
    page = pdf.new_page(width=600, height=800)
    page.insert_text((50, 55), "Clinical Summary", fontsize=16)
    page.insert_text((50, 82), "The patient reported mild dizziness during the visit.", fontsize=11)
    # A bordered 2x2 table is reliably detected by PyMuPDF's layout table finder.
    x0, y0, x1, y1 = 50, 125, 350, 205
    for x in (x0, 200, x1):
        page.draw_line((x, y0), (x, y1), color=(0, 0, 0), width=1)
    for y in (y0, 165, y1):
        page.draw_line((x0, y), (x1, y), color=(0, 0, 0), width=1)
    page.insert_text((60, 150), "Measure", fontsize=10)
    page.insert_text((210, 150), "Value", fontsize=10)
    page.insert_text((60, 190), "Blood pressure", fontsize=10)
    page.insert_text((210, 190), "128/82 mmHg", fontsize=10)
    page.insert_image(fitz.Rect(50, 270, 300, 420), stream=image)
    return pdf.tobytes()


def test_pdf_extracts_ordered_text_table_and_visual_with_context():
    elements = extract_document_elements(make_mixed_pdf(), "mixed.pdf", "application/pdf")
    kinds = [element["element_type"] for element in elements]

    assert "text" in kinds
    assert "table" in kinds
    assert "image" in kinds
    assert kinds.index("text") < kinds.index("table") < kinds.index("image")
    table = next(element for element in elements if element["element_type"] == "table")
    assert "Blood pressure" in table["text"]
    image = next(element for element in elements if element["element_type"] == "image")
    assert image["image_bytes"].startswith(b"\x89PNG")
    assert image["page_number"] == 1


def test_text_upload_keeps_legacy_page_compatibility():
    elements = extract_document_elements(b"hello world", "note.txt", "text/plain")
    assert elements == [{"page_number": None, "element_type": "text",
                         "section_title": None, "text": "hello world"}]


def test_pdf_page_limit_is_bounded():
    pdf = fitz.open()
    for _ in range(MAX_PDF_PAGES + 1):
        pdf.new_page()
    with pytest.raises(HTTPException) as error:
        extract_document_elements(pdf.tobytes(), "long.pdf", "application/pdf")
    assert error.value.status_code == 413
