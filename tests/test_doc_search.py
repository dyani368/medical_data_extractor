from unittest.mock import MagicMock
from types import SimpleNamespace

from sqlalchemy.dialects import postgresql

from app.services import doc_search


def test_search_query_is_filtered_to_authenticated_user(monkeypatch):
    monkeypatch.setattr(doc_search, "embed_text", lambda query: [0.0] * 384)
    db = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = []

    doc_search.generate_relevant_docs("blood pressure", limit=2, user_id=42, db=db)

    for call in db.execute.call_args_list:
        compiled = call.args[0].compile(dialect=postgresql.dialect())
        assert "documents.user_id =" in str(compiled)
        assert 42 in compiled.params.values()
        assert "LIMIT" in str(compiled)
        assert "<= " not in str(compiled)


def test_rank_fusion_rewards_agreement_and_deduplicates():
    a, b, c = [SimpleNamespace(id=n) for n in (1, 2, 3)]
    assert [doc.id for doc in doc_search.fuse_rankings([a, b], [b, c], 3)] == [2, 1, 3]


def test_explicit_cutoff_is_opt_in(monkeypatch):
    monkeypatch.setattr(doc_search, "embed_text", lambda query: [0.0] * 384)
    db = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = []
    doc_search.generate_relevant_docs("query", 2, 42, db, threshold=0.45)
    assert db.execute.call_count == 1
    assert 0.45 in db.execute.call_args.args[0].compile().params.values()


def test_long_question_uses_bounded_or_query_when_exact_terms_find_nothing(monkeypatch):
    monkeypatch.setattr(doc_search, "embed_text", lambda query: [0.0] * 384)
    db = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = []
    doc_search.generate_relevant_docs(
        "What was the total short-term net gain or loss on the Summary Information page?",
        5, 42, db,
    )
    assert db.execute.call_count == 3
    fallback = db.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    assert "documents.user_id =" in str(fallback)
    assert any("total | short | term | net | gain | or | loss" in str(value)
               for value in fallback.params.values())


def test_document_scope_applies_to_every_retrieval_query(monkeypatch):
    monkeypatch.setattr(doc_search, "embed_text", lambda query: [0.0] * 384)
    db = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = []

    doc_search.generate_relevant_docs("reported amount", 5, 42, db,
                                      source_document_id="selected-upload")

    assert db.execute.call_count == 3
    for call in db.execute.call_args_list:
        compiled = call.args[0].compile(dialect=postgresql.dialect())
        assert "documents.user_id =" in str(compiled)
        assert "documents.source_document_id =" in str(compiled)
        assert 42 in compiled.params.values()
        assert "selected-upload" in compiled.params.values()
