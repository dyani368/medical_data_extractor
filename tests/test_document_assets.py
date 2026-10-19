import pytest

from app.core.config import settings
from app.services import document_assets


def test_upload_and_visual_assets_are_private_and_removable(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "document_asset_dir", str(tmp_path))
    source_id = "c2ed66df-e674-4ae7-8248-8f57bcf98b4a"
    source_ref = document_assets.persist_source_upload(b"private pdf", 42, source_id)
    assert document_assets.read_asset(source_ref, 42) == b"private pdf"

    elements = document_assets.persist_elements([{
        "page_number": 1, "element_type": "image", "image_bytes": b"fake-png",
        "image_mime": "image/png", "text": "",
    }], 42, source_id)
    assert document_assets.read_asset(elements[0]["asset_ref"], 42) == b"fake-png"
    with pytest.raises(FileNotFoundError):
        document_assets.read_asset(elements[0]["asset_ref"], 99)

    document_assets.delete_document_assets(42, source_id)
    with pytest.raises(FileNotFoundError):
        document_assets.read_asset(source_ref, 42)


def test_asset_paths_cannot_escape_account_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "document_asset_dir", str(tmp_path))
    with pytest.raises(FileNotFoundError):
        document_assets.resolve_asset("99/secret.png", 42)
