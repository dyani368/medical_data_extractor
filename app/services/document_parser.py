"""Bounded, layout-aware extraction of PDF text, tables, and visual evidence."""
from io import BytesIO
from pathlib import Path

import fitz
from fastapi import HTTPException, status

MAX_UPLOAD_BYTES = 20_000_000
MAX_PDF_PAGES = 100
MAX_IMAGE_BYTES = 3_000_000
MAX_IMAGES_PER_PDF = 30
MIN_IMAGE_SIDE = 48


def validate_document_upload(content: bytes, filename: str | None, content_type: str | None) -> None:
    suffix = Path(filename or "").suffix.lower()
    if content_type == "text/plain" or suffix == ".txt":
        try:
            text = content.decode("utf-8").replace("\x00", "").strip()
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="Text uploads must use UTF-8") from exc
        if not text:
            raise HTTPException(status_code=400, detail="Document is empty")
        return
    if content_type != "application/pdf" and suffix != ".pdf":
        raise HTTPException(status_code=400, detail="Upload a UTF-8 .txt file or a .pdf file")
    if not content.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="File is not a valid PDF")


def _table_markdown(rows):
    rows = [[" ".join(str(cell or "").split()) for cell in row] for row in rows if row]
    if not rows:
        return ""
    width = max(map(len, rows))
    rows = [row + [""] * (width - len(row)) for row in rows]
    header = rows[0]
    body = rows[1:] or [[""] * width]
    return "\n".join([
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
        *("| " + " | ".join(row) + " |" for row in body),
    ])


def _overlap_ratio(rect, other):
    intersection = rect & other
    if intersection.is_empty or rect.is_empty:
        return 0.0
    return intersection.get_area() / max(rect.get_area(), 1.0)


def _heading_for_y(blocks, y):
    candidates = []
    for block in blocks:
        if block.get("type") != 0 or block.get("bbox", [0, 0, 0, 0])[1] > y:
            continue
        text = " ".join(span.get("text", "") for line in block.get("lines", [])
                        for span in line.get("spans", [])).strip()
        size = max((span.get("size", 0) for line in block.get("lines", [])
                    for span in line.get("spans", [])), default=0)
        if text and size >= 12:
            candidates.append((block["bbox"][1], text[:200]))
    return max(candidates, default=(0, None), key=lambda item: item[0])[1]


def _nearby_text(blocks, y, radius=120):
    nearby = []
    for block in blocks:
        if block.get("type") != 0:
            continue
        y0, y1 = block.get("bbox", (0, 0, 0, 0))[1:3]
        if y1 < y - radius or y0 > y + radius:
            continue
        text = " ".join(span.get("text", "") for line in block.get("lines", [])
                        for span in line.get("spans", [])).strip()
        if text:
            nearby.append((y0, text))
    return " ".join(text for _, text in sorted(nearby))[:1200]


def extract_document_elements(content: bytes, filename: str | None, content_type: str | None) -> list[dict]:
    """Return ordered page elements. Image bytes remain transient until queued assets are persisted."""
    validate_document_upload(content, filename, content_type)
    suffix = Path(filename or "").suffix.lower()
    if content_type == "text/plain" or suffix == ".txt":
        try:
            text = content.decode("utf-8").replace("\x00", "").strip()
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="Text uploads must use UTF-8") from exc
        if not text:
            raise HTTPException(status_code=400, detail="Document is empty")
        return [{"page_number": None, "element_type": "text", "section_title": None, "text": text}]

    if content_type != "application/pdf" and suffix != ".pdf":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Upload a UTF-8 .txt file or a .pdf file")
    if not content.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="File is not a valid PDF")

    try:
        pdf = fitz.open(stream=BytesIO(content), filetype="pdf")
        if pdf.is_encrypted:
            raise HTTPException(status_code=400, detail="Encrypted PDFs are not supported")
        if pdf.page_count > MAX_PDF_PAGES:
            raise HTTPException(status_code=413, detail=f"PDF exceeds the {MAX_PDF_PAGES} page limit")

        elements = []
        visual_count = 0
        for page_index, page in enumerate(pdf):
            page_number = page_index + 1
            blocks = page.get_text("dict").get("blocks", [])
            tables = []
            table_rects = []
            try:
                for table in page.find_tables().tables:
                    rendered = _table_markdown(table.extract())
                    if rendered:
                        table_rects.append(fitz.Rect(table.bbox))
                        tables.append({"page_number": page_number, "element_type": "table",
                                       "section_title": _heading_for_y(blocks, table.bbox[1]),
                                       "text": rendered, "bbox": list(table.bbox)})
            except (AttributeError, ValueError, RuntimeError):
                # A malformed/vector-heavy page should still yield its text and images.
                pass

            text_parts = []
            for block in blocks:
                if block.get("type") != 0:
                    continue
                rect = fitz.Rect(block.get("bbox", (0, 0, 0, 0)))
                if any(_overlap_ratio(rect, table_rect) >= 0.5 for table_rect in table_rects):
                    continue
                block_text = "\n".join("".join(span.get("text", "") for span in line.get("spans", []))
                                       for line in block.get("lines", [])).strip()
                if block_text:
                    text_parts.append((rect.y0, {"page_number": page_number, "element_type": "text",
                        "section_title": _heading_for_y(blocks, rect.y0), "text": block_text,
                        "bbox": list(rect)}))

            page_elements = text_parts + [(fitz.Rect(item["bbox"]).y0, item) for item in tables]

            for image_index, image_info in enumerate(page.get_images(full=True), start=1):
                if visual_count >= MAX_IMAGES_PER_PDF:
                    break
                try:
                    extracted = pdf.extract_image(image_info[0])
                    image_bytes = extracted["image"]
                    extension = extracted.get("ext", "png").lower()
                    if extension not in {"png", "jpeg"}:
                        pixmap = fitz.Pixmap(pdf, image_info[0])
                        if pixmap.n - pixmap.alpha > 3:
                            pixmap = fitz.Pixmap(fitz.csRGB, pixmap)
                        image_bytes, extension = pixmap.tobytes("png"), "png"
                    width, height = extracted.get("width", 0), extracted.get("height", 0)
                    if (len(image_bytes) > MAX_IMAGE_BYTES or min(width, height) < MIN_IMAGE_SIDE
                            or width * height < 10_000):
                        continue
                    rects = page.get_image_rects(image_info[0])
                    y = rects[0].y0 if rects else page.rect.height
                    page_elements.append((y, {"page_number": page_number, "element_type": "image",
                        "section_title": _heading_for_y(blocks, y), "context_text": _nearby_text(blocks, y), "text": "",
                        "image_bytes": image_bytes, "image_mime": "image/jpeg" if extension == "jpeg" else "image/png",
                        "bbox": list(rects[0]) if rects else None}))
                    visual_count += 1
                except (KeyError, ValueError, RuntimeError):
                    continue

            # Vector charts/diagrams have no embedded image object. Render only pages
            # with substantial vector drawing and useful text, avoiding whole-PDF rasterization.
            if visual_count < MAX_IMAGES_PER_PDF:
                drawings = page.get_drawings()
                if len(drawings) >= 50:
                    pixmap = page.get_pixmap(matrix=fitz.Matrix(1.4, 1.4), alpha=False)
                    image_bytes = pixmap.tobytes("png")
                    if len(image_bytes) <= MAX_IMAGE_BYTES:
                        page_context = " ".join(
                            " ".join(span.get("text", "") for line in block.get("lines", [])
                                     for span in line.get("spans", []))
                            for block in blocks if block.get("type") == 0
                        )[:1200]
                        page_elements.append((0, {"page_number": page_number, "element_type": "image",
                            "section_title": _heading_for_y(blocks, page.rect.height), "context_text": page_context, "text": "",
                            "image_bytes": image_bytes, "image_mime": "image/png", "bbox": None}))
                        visual_count += 1

            page_elements.sort(key=lambda pair: pair[0])
            elements.extend(item for _, item in page_elements)

        if not elements:
            raise HTTPException(status_code=400, detail="PDF contains no extractable text or visual content")
        return elements
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Could not parse PDF content") from exc


def extract_document_pages(content: bytes, filename: str | None, content_type: str | None) -> list[tuple[int | None, str]]:
    """Compatibility helper for text-only callers and older tests."""
    return [(item.get("page_number"), item["text"]) for item in
            extract_document_elements(content, filename, content_type) if item.get("text", "").strip()]


def extract_document_text(content: bytes, filename: str | None, content_type: str | None) -> str:
    return "\n".join(text for _, text in extract_document_pages(content, filename, content_type))
