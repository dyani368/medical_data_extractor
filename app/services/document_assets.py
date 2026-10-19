"""Private local asset storage shared by the API and ingestion worker containers."""
import base64
from pathlib import Path
import shutil
import time
import uuid

from app.core.config import settings


def _root() -> Path:
    root = Path(settings.document_asset_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def persist_elements(elements: list[dict], user_id: int, source_document_id: str) -> list[dict]:
    """Persist extracted image bytes privately and return JSON-safe queue elements."""
    elements = [item if isinstance(item, dict) else {
        "page_number": item[0], "element_type": "text", "section_title": None, "text": item[1]
    } for item in elements]
    try:
        uuid.UUID(source_document_id)
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid document asset namespace") from exc
    root = _root()
    directory = root / str(user_id) / source_document_id
    has_images = any(item.get("image_bytes") for item in elements)
    if has_images:
        directory.mkdir(parents=True, exist_ok=True)
    safe = []
    try:
        for index, item in enumerate(elements):
            copied = {key: value for key, value in item.items() if key != "image_bytes"}
            image = item.get("image_bytes")
            if image:
                suffix = ".jpg" if item.get("image_mime") == "image/jpeg" else ".png"
                name = f"visual-{index:04d}{suffix}"
                target = directory / name
                target.write_bytes(image)
                copied["asset_ref"] = f"{user_id}/{source_document_id}/{name}"
            safe.append(copied)
        return safe
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise


def persist_source_upload(content: bytes, user_id: int, source_document_id: str) -> str:
    """Keep the original upload until a worker has durably partitioned it."""
    try:
        uuid.UUID(source_document_id)
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid document upload namespace") from exc
    root = _root()
    directory = root / str(user_id)
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{source_document_id}.upload"
    (directory / name).write_bytes(content)
    return f"{user_id}/{name}"


def preserve_source_upload(user_id: int, source_document_id: str, source_ref: str,
                           filename: str) -> None:
    """Keep a private original for the authenticated document review screen.

    Copy rather than move: a worker crash before the partition checkpoint must
    leave the staging upload available for a safe retry.
    """
    source = resolve_asset(source_ref, user_id)
    if Path(filename).suffix.lower() != ".pdf":
        return
    directory = _root() / str(user_id) / source_document_id
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "source.pdf"
    temporary = directory / "source.pdf.part"
    shutil.copyfile(source, temporary)
    temporary.replace(target)


def resolve_document_source(user_id: int, source_document_id: str) -> Path:
    try:
        uuid.UUID(source_document_id)
    except (TypeError, ValueError) as exc:
        raise FileNotFoundError("Original document not available") from exc
    return resolve_asset(f"{user_id}/{source_document_id}/source.pdf", user_id)


def delete_source_upload(user_id: int, source_ref: str) -> None:
    try:
        resolve_asset(source_ref, user_id).unlink(missing_ok=True)
    except FileNotFoundError:
        return


def resolve_asset(asset_ref: str, user_id: int) -> Path:
    root = _root()
    candidate = (root / asset_ref).resolve()
    try:
        candidate.relative_to(root / str(user_id))
    except ValueError as exc:
        raise FileNotFoundError("Visual asset not found") from exc
    if not candidate.is_file():
        raise FileNotFoundError("Visual asset not found")
    return candidate


def read_asset(asset_ref: str, user_id: int) -> bytes:
    return resolve_asset(asset_ref, user_id).read_bytes()


def read_asset_data_url(asset_ref: str, user_id: int, mime_type: str | None = None) -> str:
    path = resolve_asset(asset_ref, user_id)
    mime = mime_type or ("image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "image/png")
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def delete_document_assets(user_id: int, source_document_id: str) -> None:
    root = _root()
    directory = (root / str(user_id) / source_document_id).resolve()
    try:
        directory.relative_to(root / str(user_id))
    except ValueError:
        return
    shutil.rmtree(directory, ignore_errors=True)
    delete_source_upload(user_id, f"{user_id}/{source_document_id}.upload")


def cleanup_orphan_source_uploads(active_refs: set[str], minimum_age_seconds: int = 86_400) -> int:
    """Remove stale raw uploads left by crashes before a queue row was committed."""
    cutoff = time.time() - minimum_age_seconds
    root = _root()
    removed = 0
    for directory in root.iterdir():
        if not directory.is_dir() or not directory.name.isdigit():
            continue
        user_id = int(directory.name)
        for path in directory.glob("*.upload"):
            reference = f"{user_id}/{path.name}"
            try:
                if reference not in active_refs and path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
                    removed += 1
            except OSError:
                continue
    return removed
