from tools.run_rag_eval import expected_source_rank, summarize


def test_expected_source_rank_matches_original_filename_and_chunks():
    question = {"document_id": "chart"}
    docs = {"chart": {"filename": "09_symptom_trend_chart.pdf"}}
    results = [
        {"filename": "other.pdf", "content": "irrelevant"},
        {"filename": "09_symptom_trend_chart_chunk_2", "content": "caption"},
    ]
    assert expected_source_rank(question, results, docs) == 2


def test_summary_reports_source_recall_and_mrr_without_changing_quote_metric():
    rows = [
        {"endpoint": "search", "http_status": "200", "latency_ms": "100",
         "answerable": "true", "retrieval_hit": "false", "expected_filename": "chart.pdf",
         "source_rank_at_5": "2"},
        {"endpoint": "search", "http_status": "200", "latency_ms": "200",
         "answerable": "true", "retrieval_hit": "true", "expected_filename": "note.pdf",
         "source_rank_at_5": ""},
        {"endpoint": "chat/agent", "http_status": "200", "latency_ms": "1000",
         "answerable": "true", "privacy_test": "false", "multimodal_test": "true",
         "answer_correct": "partial", "refusal_correct": "yes", "citation_supported": "yes",
         "privacy_safe": "", "expected_filename": "chart.pdf", "source_rank_at_5": ""},
    ]
    metrics = summarize(rows)
    assert metrics["retrieval_hit_at_5"] == {"hits": 1, "answerable_questions": 2, "rate": 0.5}
    assert metrics["expected_source_recall_at_5"] == {"hits": 1, "questions": 2, "rate": 0.5}
    assert metrics["expected_source_mrr_at_5"]["rate"] == 0.25
    assert metrics["multimodal_agent_answers"]["partial"] == 1
