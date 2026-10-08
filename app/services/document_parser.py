from io import BytesIO
from pathlib import Path

from fastapi import HTTPException, status
from pypdf import PdfReader

MAX_UPLOAD_BYTES = 5_000_000
MAX_PDF_PAGES = 30


def extract_document_text(content: bytes, filename: str | None, content_type: str | None) -> str:
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
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Could not read PDF text") from exc
        if not text.strip():
            raise HTTPException(status_code=400, detail="PDF contains no extractable text; scanned PDFs are not supported")
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Upload a UTF-8 .txt file or a text-based .pdf file")

    text = text.replace("\x00", "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Document is empty")
    return text
