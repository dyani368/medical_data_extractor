"""Exercise the public UI/API origin with a disposable synthetic-data account.

Creates its own account. Deletes the uploaded document unless --keep-document
is used for a manual browser review. Credentials are never printed.
"""
import argparse
import json
from pathlib import Path
import secrets
import time

import httpx


def chat(client, query, conversation_id=None):
    payload = {"query": query}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    answer, sources, event, data, completed = "", [], "message", [], False
    with client.stream("POST", "/api/chat/stream", json=payload, timeout=180) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].removeprefix(" "))
            elif not line:
                value = "\n".join(data)
                if event == "conversation":
                    conversation_id = json.loads(value)["conversation_id"]
                elif event == "sources":
                    sources = json.loads(value)
                elif event == "error":
                    raise RuntimeError(json.loads(value)["message"])
                elif event == "complete":
                    completed = True
                else:
                    answer += value
                event, data = "message", []
    assert completed, "Stream did not report completion"
    return answer, sources, conversation_id


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument("--existing-account", action="store_true")
    parser.add_argument("--document-id", help="Resume checks against a previously uploaded test document")
    parser.add_argument("--keep-document", action="store_true")
    args = parser.parse_args()
    username = args.username or "ui_smoke_" + secrets.token_hex(5)
    password = args.password or secrets.token_urlsafe(30)
    sample = Path(__file__).resolve().parents[1] / "frontend/public/samples/cardiovascular-followup.pdf"
    document_id = None
    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=35) as client:
        client.get("/api/health/ready").raise_for_status()
        if not args.existing_account:
            registered = client.post("/api/register", json={"username": username, "email": username + "@example.com", "password": password})
            registered.raise_for_status()
        token = client.post("/api/token", data={"username": username, "password": password})
        token.raise_for_status()
        client.headers["Authorization"] = "Bearer " + token.json()["access_token"]
        assert client.get("/api/me").json()["username"] == username
        print("PASS register, login, and profile", flush=True)
        try:
            if args.document_id:
                document_id = args.document_id
            else:
                uploaded = client.post("/api/upload", files={"file": (sample.name, sample.read_bytes(), "application/pdf")}, headers={"Idempotency-Key": secrets.token_hex(16)})
                uploaded.raise_for_status()
                document_id = uploaded.json()["document_id"]
            deadline = time.monotonic() + 240
            while time.monotonic() < deadline:
                job = client.get("/api/jobs/" + document_id)
                job.raise_for_status()
                state = job.json()
                if state["status"] in ("completed", "completed_with_errors", "failed"):
                    assert state["status"] == "completed", f"Ingestion outcome: {state['status']}"
                    break
                time.sleep(2)
            else:
                raise RuntimeError("Ingestion did not finish within four minutes")
            detail = client.get("/api/documents/" + document_id).json()
            extraction = client.get("/api/documents/" + document_id + "/extraction").json()
            assert detail["chunks"] and all(item["status"] == "succeeded" for item in extraction["items"])
            assert all(chunk["page_number"] for chunk in detail["chunks"])
            print("PASS PDF ingestion, job polling, document detail, and extraction", flush=True)
            answer, sources, conversation_id = chat(client, "What symptom and blood pressure were recorded in the cardiovascular follow-up?")
            assert "160/95" in answer and "dizziness" in answer.lower(), "First answer did not contain expected facts"
            assert sources and conversation_id
            passage = client.get(f"/api/chunks/{sources[0]['document_id']}")
            passage.raise_for_status()
            assert passage.json()["content"]
            followup, followup_sources, continued_id = chat(client, "Did this patient report chest pain or shortness of breath?", conversation_id)
            assert continued_id == conversation_id and followup_sources
            assert any(word in followup.lower() for word in ("denied", "no ", "not report", "did not")), "Follow-up lost the record context"
            history = client.get(f"/api/conversations/{conversation_id}").json()
            assert len(history["messages"]) >= 4
            assert client.get("/api/conversations").json()["items"][0]["title"]
            print("PASS streamed answer, cited passage, conversation ID, follow-up, and history", flush=True)
            invalid = client.post("/api/upload", files={"file": ("not-a-pdf.pdf", b"not a PDF", "application/pdf")})
            assert invalid.status_code == 400
            print("PASS invalid-file rejection", flush=True)
            print(json.dumps({"username": username, "document_id": document_id, "conversation_id": conversation_id, "checks": "passed"}), flush=True)
        finally:
            if document_id and not args.keep_document:
                deleted = client.delete("/api/documents/" + document_id)
                deleted.raise_for_status()
                assert client.get("/api/documents/" + document_id).status_code == 404
                print("PASS document deletion", flush=True)


if __name__ == "__main__":
    main()
