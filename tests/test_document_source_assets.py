import uuid

import pytest

from app.services import document_assets


def test_original_pdf_is_preserved_without_consuming_retry_upload(monkeypatch, tmp_path):
    monkeypatch.setattr(document_assets.settings, "document_asset_dir", str(tmp_path))
    document_id = str(uuid.uuid4())
    content = b"%PDF-1.4\nprivate example"
    staged = document_assets.persist_source_upload(content, 42, document_id)

    document_assets.preserve_source_upload(42, document_id, staged, "record.pdf")

    assert document_assets.read_asset(staged, 42) == content
    assert document_assets.resolve_document_source(42, document_id).read_bytes() == content
    with pytest.raises(FileNotFoundError):
        document_assets.resolve_document_source(99, document_id)

    document_assets.delete_source_upload(42, staged)
    assert document_assets.resolve_document_source(42, document_id).read_bytes() == content
    document_assets.delete_document_assets(42, document_id)
    with pytest.raises(FileNotFoundError):
        document_assets.resolve_document_source(42, document_id)
