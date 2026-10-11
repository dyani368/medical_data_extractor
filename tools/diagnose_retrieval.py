"""Read-only embedding diagnostics for synthetic demo documents; never prints credentials."""
import os
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("HF_HUB_OFFLINE", "1")
from sqlalchemy import text, create_engine
from app.core.config import settings
from app.core.embeddings import embed_text


def main(user_id):
    print("Connecting to database (read-only)...", flush=True)
    engine = create_engine(settings.database_url, connect_args={"connect_timeout": 10})
    queries = [
        "What adverse event was reported?",
        "Did the patient report chest pain or shortness of breath?",
        "What blood pressure and symptom were recorded in the cardiovascular follow-up?",
    ]
    with engine.connect() as connection:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        for query in queries:
            print("Embedding:", query, flush=True)
            vector = str(embed_text(query))
            rows = connection.execute(text(
                "SELECT id, user_id, filename, embedding <=> CAST(:vector AS vector) AS distance, "
                "raw_content FROM documents WHERE filename LIKE 'synthetic_%' AND user_id = :user_id "
                "ORDER BY distance LIMIT 8"
            ), {"vector": vector, "user_id": user_id}).mappings().all()
            print(query, flush=True)
            for row in rows:
                print(dict(row), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", type=int, required=True)
    args = parser.parse_args()
    try:
        main(args.user_id)
    except Exception as error:
        print("Diagnostics failed:", type(error).__name__)
        sys.exit(1)
