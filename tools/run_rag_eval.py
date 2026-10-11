"""Run retrieval/chat timing and capture outputs for manual answer/citation grading.

PowerShell setup:
  $env:EVAL_BASE_URL = 'http://localhost:8000'
  $env:EVAL_API_TOKEN = '<paste a short-lived bearer token>'
  python tools/run_rag_eval.py --repeats 1
"""
import argparse
import csv
import json
import os
import re
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "eval" / "corpus.json"
RESULTS = ROOT / "eval" / "results.csv"
SUMMARY = ROOT / "eval" / "summary.json"
MANUAL_FIELDS = ("answer_correct", "refusal_correct", "citation_supported", "privacy_safe")


def percentile(values, percent):
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percent / 100
    lower, upper = int(rank), min(int(rank) + 1, len(ordered) - 1)
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower), 1)


def norm(value):
    return " ".join("".join(c.lower() if c.isalnum() else " " for c in value).split())


def recall_hit(question, results):
    quote = question.get("evidence_quote")
    if not question["answerable"] or not quote:
        return ""
    expected = norm(quote)
    passages = " ".join(norm(item.get("content", "")) for item in results)
    return str(expected in passages).lower()


def summarize(rows):
    metrics = {}
    for endpoint in ("search", "agent"):
        aliases = {"agent", "chat/agent"} if endpoint == "agent" else {endpoint}
        matching = [r for r in rows if r["endpoint"].strip("/") in aliases and r["http_status"] == "200"]
        durations = [float(r["latency_ms"]) for r in matching]
        metrics[endpoint] = {
            "successful_requests": len(matching),
            "median_latency_ms": percentile(durations, 50),
            "p95_latency_ms": percentile(durations, 95),
        }
    search_rows = [r for r in rows if r["endpoint"] == "search" and r["answerable"] == "true"]
    metrics["retrieval_hit_at_5"] = {
        "hits": sum(r["retrieval_hit"] == "true" for r in search_rows),
        "answerable_questions": len(search_rows),
        "rate": round(sum(r["retrieval_hit"] == "true" for r in search_rows) / len(search_rows), 4) if search_rows else None,
    }
    agent_rows = [r for r in rows if r["endpoint"].strip("/") in {"agent", "chat/agent"}]
    for field in MANUAL_FIELDS:
        eligible = [r for r in agent_rows if field != "privacy_safe" or r.get("privacy_test", "").lower() == "true"]
        labels = [r.get(field, "").strip().lower() for r in eligible]
        graded = [label for label in labels if label in {"yes", "no"}]
        partial = labels.count("partial")
        metrics[field] = {"yes": graded.count("yes"), "partial": partial,
                          "no": graded.count("no"), "ungraded": len(eligible)-len(graded)-partial}
    metrics["note"] = "Small synthetic demo benchmark. Manual judgments are not inferred by the script."
    return metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--base-url", default=os.getenv("EVAL_BASE_URL", "http://localhost:8000"))
    parser.add_argument("--token", default=os.getenv("EVAL_API_TOKEN"))
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args()
    if args.summary_only:
        with RESULTS.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
    else:
        if not args.token:
            parser.error("Set EVAL_API_TOKEN or pass --token. The token is never written to results.")
        if not 1 <= args.repeats <= 20:
            parser.error("--repeats must be between 1 and 20")
        corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
        headers = {"Authorization": f"Bearer {args.token}"}
        rows = []
        with httpx.Client(base_url=args.base_url.rstrip("/"), headers=headers, timeout=120) as client:
            for repeat in range(1, args.repeats + 1):
                conversations = {}
                for question in corpus["questions"]:
                    group = question.get("conversation_group")
                    for endpoint in ("search", "chat/agent"):
                        conversation_id = None
                        payload = {"query": question["query"]}
                        if endpoint == "chat/agent" and group in conversations:
                            payload["conversation_id"] = conversations[group]
                        started = time.perf_counter()
                        try:
                            response = client.post("/" + endpoint, json=payload)
                            elapsed = round((time.perf_counter() - started) * 1000, 1)
                            try:
                                body = response.json()
                            except ValueError:
                                body = {"raw": response.text[:4000]}
                            if endpoint == "search":
                                results = body if isinstance(body, list) else []
                                retrieval_hit = recall_hit(question, results)
                            else:
                                results = []
                                retrieval_hit = ""
                                conversation_id = body.get("conversation_id") if isinstance(body, dict) else None
                                if endpoint == "chat/agent" and group and conversation_id:
                                    conversations[group] = conversation_id
                            cited = sorted(set(re.findall(r"(?:\[doc:|【(?:doc:)?)(\d+)(?:\]|】)",
                                                          body.get("response", "") if isinstance(body, dict) else "")))
                            rows.append({
                                "run_at_utc": datetime.now(timezone.utc).isoformat(),
                                "repeat": repeat, "question_id": question["id"], "endpoint": endpoint,
                                "answerable": str(question["answerable"]).lower(),
                                "privacy_test": str(question.get("privacy_test", False)).lower(),
                                "expected_document": question.get("document_id") or "",
                                "expected_facts": json.dumps(question.get("expected_facts", []), ensure_ascii=False),
                                "evidence_quote": question.get("evidence_quote") or "",
                                "http_status": str(response.status_code), "latency_ms": elapsed,
                                "retrieval_hit": retrieval_hit,
                                "cited_document_ids": json.dumps(cited),
                                "conversation_id": conversation_id or "",
                                "response": json.dumps(body, ensure_ascii=False),
                                **{field: "" for field in MANUAL_FIELDS},
                            })
                        except httpx.HTTPError as error:
                            elapsed = round((time.perf_counter() - started) * 1000, 1)
                            rows.append({"run_at_utc": datetime.now(timezone.utc).isoformat(),
                                "repeat": repeat, "question_id": question["id"], "endpoint": endpoint,
                                "answerable": str(question["answerable"]).lower(),
                                "privacy_test": str(question.get("privacy_test", False)).lower(),
                                "expected_document": question.get("document_id") or "",
                                "expected_facts": json.dumps(question.get("expected_facts", []), ensure_ascii=False),
                                "evidence_quote": question.get("evidence_quote") or "",
                                "http_status": "ERROR", "latency_ms": elapsed,
                                "retrieval_hit": "", "cited_document_ids": "[]", "conversation_id": "",
                                "response": type(error).__name__, **{field: "" for field in MANUAL_FIELDS}})
                    print(f"repeat {repeat}: {question['id']} done", flush=True)
        RESULTS.parent.mkdir(parents=True, exist_ok=True)
        old = []
        if RESULTS.exists():
            with RESULTS.open(encoding="utf-8-sig", newline="") as stream:
                old = list(csv.DictReader(stream))
            # Keep prior manual grades when replacing the same question/repeat/endpoint.
            prior = {(r["question_id"], r["repeat"], r["endpoint"]): r for r in old}
            for row in rows:
                existing = prior.get((row["question_id"], row["repeat"], row["endpoint"]))
                if existing:
                    for field in MANUAL_FIELDS:
                        row[field] = existing.get(field, "")
        fields = list(rows[0]) if rows else []
        with RESULTS.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    metrics = summarize(rows)
    SUMMARY.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    print(f"Results CSV: {RESULTS}\nSummary JSON: {SUMMARY}")
    print("Manually fill answer_correct, refusal_correct, citation_supported, privacy_safe with yes/no/partial; then run --summary-only.")


if __name__ == "__main__":
    main()
