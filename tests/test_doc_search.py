from unittest.mock import MagicMock

from sqlalchemy.dialects import postgresql

from app.services import doc_search


def test_search_query_is_filtered_to_authenticated_user(monkeypatch):
    monkeypatch.setattr(doc_search, "embed_text", lambda query: [0.0] * 384)
    db = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = []

    doc_search.generate_relevant_docs("blood pressure", limit=2, user_id=42, db=db)

    statement = db.execute.call_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert "documents.user_id =" in str(compiled)
    assert 42 in compiled.params.values()
    assert "LIMIT" in str(compiled)
