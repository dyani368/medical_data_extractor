from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.services.conversation_service import get_or_create_conversation


def test_missing_or_unowned_conversation_does_not_create_new_chat():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    with pytest.raises(HTTPException) as error:
        get_or_create_conversation(db, 42, 123)
    assert error.value.status_code == 404
    db.add.assert_not_called()


def test_owned_conversation_is_reused():
    db = MagicMock()
    from types import SimpleNamespace
    existing = SimpleNamespace(source_document_id=None)
    db.query.return_value.filter.return_value.first.return_value = existing
    assert get_or_create_conversation(db, 42, 123) is existing
    db.add.assert_not_called()


def test_conversation_cannot_switch_document_scope():
    from types import SimpleNamespace
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
        source_document_id="document-a")
    with pytest.raises(HTTPException) as error:
        get_or_create_conversation(db, 42, 123, "document-b")
    assert error.value.status_code == 400
