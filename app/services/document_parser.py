from io import BytesIO
from pathlib import Path

from fastapi import HTTPException, status
from pypdf import PdfReader

MAX_UPLOAD_BYTES = 5_000_000
MAX_PDF_PAGES = 30


def extract_document_pages(content: bytes, filename: str | None, content_type: str | None) -> list[tuple[int | None, str]]:
    suffix = Path(filename or "").suffix.lower()

    if content_type == "text/plain" or suffix == ".txt":
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="Text uploads must use UTF-8") from exc
    elif content_type == "application/pdf" or suffix == ".pdf":
        if not content.startswith(b"%PDF-"):
            raise HTTPException(status_code=400, detail="File is not a valid PDF")
        try:
            reader = PdfReader(BytesIO(content), strict=True)
            if reader.is_encrypted:
                raise HTTPException(status_code=400, detail="Encrypted PDFs are not supported")
            if len(reader.pages) > MAX_PDF_PAGES:
                raise HTTPException(status_code=413, detail="PDF exceeds the 30 page limit")
            pages = [(index + 1, (page.extract_text() or "").replace("\x00", "").strip())
                     for index, page in enumerate(reader.pages)]
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Could not read PDF text") from exc
        if not any(text for _, text in pages):
            raise HTTPException(status_code=400, detail="PDF contains no extractable text; scanned PDFs are not supported")
        return [(page_number, text) for page_number, text in pages if text]
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Upload a UTF-8 .txt file or a text-based .pdf file")

    text = text.replace("\x00", "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Document is empty")
    return [(None, text)]


def extract_document_text(content: bytes, filename: str | None, content_type: str | None) -> str:
    return "\n".join(text for _, text in extract_document_pages(content, filename, content_type))
