# Clinical AI Extraction & Orchestration Pipeline (POC)

A portfolio proof of concept demonstrating background ingestion, structured data extraction, semantic search, and clinical question answering over synthetic records. It explores production-oriented patterns but is not validated for clinical use or real patient data.

---

## Features

- **Background Ingestion:** Accepts UTF-8 text and text-based PDFs, extracts PDF text locally, then uses `FastAPI.BackgroundTasks` and Redis job status (`GET /jobs/{job_id}`). A process restart can lose unfinished jobs.
- **Retry Handling:** An `Idempotency-Key` on `/upload` lets a user retrieve a previously accepted job for 24 hours. This is a best-effort retry mechanism, not exactly-once processing.
- **AI-Powered Structured Extraction:** Extracts structured fields (summary, category, key entities, confidence score) using Groq and Pydantic validation.
- **Recursive Document Chunking:** Splits large clinical records using `RecursiveCharacterTextSplitter` (500 characters, 50 overlap) for high-granularity vector storage and retrieval.
- **Semantic Vector Search:** Embeds clinical text into 384-dimensional dense vectors using HuggingFace (`sentence-transformers/all-MiniLM-L6-v2`) and runs cosine distance similarity queries via `pgvector`.
- **Evidence-Gated Clinical Q&A:** The agent stores a limited conversation history, searches only the authenticated user's records, and withholds clinical answers when no sources were retrieved. Responses include source metadata and ask the model to cite `[doc:ID]` markers.
- **Token Streaming (SSE):** `/chat/stream` emits a `sources` event followed by answer tokens when retrieval succeeds.
- **Authentication & Application-Level Isolation:** JWT authentication with Bcrypt password hashing; document searches and conversation lookups are scoped to the authenticated user. The project does not implement database row-level security.
- **Defensive Engineering & Resilience:** Retries transient LLM failures and rate limits automatically with exponential backoff (`tenacity`) and returns structured fallback schemas if APIs are unreachable.
- **Optional N8N Service:** Start the `workflow` Compose profile for local N8N experiments; no webhook or notification workflow is included.
- **Containerized Infrastructure:** Docker Compose defines PostgreSQL with `pgvector`, Redis, FastAPI, readiness checks, and optional N8N. The Dockerfile installs CPU-only PyTorch to avoid CUDA libraries on a CPU host.

---

## Tech Stack

- **API & Core:** FastAPI, Pydantic v2, SQLAlchemy 2.0, Uvicorn
- **AI & NLP:** Groq / OpenAI (`AsyncOpenAI`), HuggingFace (`sentence-transformers`), LangChain
- **Database & Vectors:** PostgreSQL 16 with `pgvector`
- **Job State:** Redis (retry keys and job status; not a durable work queue)
- **Security & Auth:** PyJWT, Passlib (Bcrypt), Presidio-based text redaction
- **Resilience:** Tenacity (exponential backoff retry policies)
- **Orchestration:** N8N, Docker & Docker Compose
- **Testing:** Pytest, Pytest-Asyncio

---

## Architecture & Flows

### 1. Asynchronous Ingestion Flow
```text
Demo client
  │
  │ HTTP POST /upload (Clinical Document) + Idempotency-Key
  ▼
FastAPI App
  │
  ├── 1. Checks Redis for an existing user-scoped job via Idempotency Key
  ├── 2. Creates unique job_id and initializes state in Redis
  ├── 3. Schedules an in-process background task and returns 202 Accepted
  │
  ▼
In-process background task
  ├── 1. Sanitizes text & chunks (500 chars / 50 overlap)
  ├── 2. Generates 384-dim embeddings per chunk (HuggingFace)
  ├── 3. LLM extracts structured JSON (summary, category, entities, confidence)
  └── 4. Updates Redis job state (`processing` -> `completed`) and persists to PostgreSQL
```

### 2. Semantic Search Flow
```text
Authenticated client (Search Query)
  │
  │ POST /search {"query": "patient adverse events on drug X"}
  ▼
FastAPI App
  │
  ├── 1. Embeds query text into 384-dimensional vector
  ├── 2. Runs SQL cosine distance query filtered by user_id
  │      (Document.embedding.cosine_distance(query_vector) <= threshold)
  │
  ▼
PostgreSQL (pgvector)
  │
  ▼
Returns top-k matching clinical document chunks
```

### 3. Unified Agentic Tool Calling & Streaming Flow (`/chat/stream` & `/chat/agent`)
```text
Demo Query: "What medications was patient PT-104 prescribed for hypertension?"
  │
  ▼
1. Agent fetches previous conversation context from PostgreSQL (Sliding Window)
  │
  ▼
2. FastAPI redacts the prompt and passes history + Tool Catalog schema to the LLM
  │
  ▼
3. LLM assesses intent. If medical context needed, emits structured tool call:
   search_medical_records(query="patient PT-104 hypertension medications")
  │
  ▼
4. Agent Service records tool execution metadata in PostgreSQL for debugging and review
  │
  ▼
5. Agent Service runs a server-scoped search:
   - Executes pgvector similarity search
   - Returns redacted chunks tagged with `[doc:ID]`
  │
  ▼
6. The response includes source metadata; the streaming endpoint emits it before answer tokens
  │
  ▼
7. Full response is saved to PostgreSQL Conversation memory
```

---

## Core API Endpoints

| Method | Endpoint | Description | Auth Required |
|---|---|---|:---:|
| `POST` | `/register` | Register a new user (clinician/researcher) | No |
| `POST` | `/token` | Obtain JWT access token via credentials | No |
| `GET` | `/me` | Fetch authenticated user profile | Yes (Bearer) |
| `POST` | `/upload` | Queue UTF-8 `.txt` or text-based `.pdf` for ingestion | Yes (Bearer) |
| `GET` | `/jobs/{job_id}` | Poll ingestion status from Redis | Yes (Bearer) |
| `POST` | `/search` | Semantic vector search across user records | Yes (Bearer) |
| `POST` | `/chat/stream` | Stream clinical QA agent answers via Server-Sent Events | Yes (Bearer) |
| `POST` | `/chat/agent` | Autonomous clinical agent with dynamic tool calling | Yes (Bearer) |
| `GET` | `/health/live` | Process liveness | No |
| `GET` | `/health/ready` | Database and Redis readiness | No |

---

## Security Design and Limits

This project uses synthetic examples only. It is a learning exercise informed by clinical data security requirements; it does **not** claim HIPAA, GDPR, or 21 CFR Part 11 compliance.

- Implemented: authenticated API access; user-scoped search, conversations, jobs, and retry keys; server-owned user scope for LLM tools; text redaction before persistence and provider calls in both ingestion paths and chat; generic errors that do not echo document text; evidence-gated answers; and tool execution metadata in PostgreSQL.
- Limits: the request body is processed in memory before redaction. Presidio can miss identifiers or remove useful clinical terms, so its output is not HIPAA Safe Harbor de-identification. Audit rows are mutable, and there is no encrypted token vault, reversible pseudonymization, database RLS, retention policy, or formal risk assessment. Existing database rows from older versions are not retroactively redacted.
- Work needed before real patient data: perform a documented risk assessment; design data minimization and access controls for every path; validate de-identification or use an appropriate authorized processing arrangement; implement encryption, retention, audit integrity, and operational controls; and obtain organizational/legal review.

| Threat or failure mode | Control in this POC | Evidence |
|---|---|---|
| Cross-user record access through model tool arguments | Server owns `user_id`, database session, and result limit | `test_agent_service.py`, `test_doc_search.py` |
| Cross-user job lookup | Owner ID stored with each job and checked on reads | `test_api_boundaries.py` |
| Identifiers sent to an external LLM | Redact input before storage and provider calls; redact retrieved chunks again | `test_privacy.py`, `test_extraction_privacy.py`, `test_agent_service.py` |
| Unsupported clinical answer | Withhold the answer when retrieval returns no sources | `test_agent_service.py` |

This is an engineering exercise, not a compliance assessment. See the [HHS de-identification guidance](https://www.hhs.gov/hipaa/for-professionals/special-topics/de-identification/index.html) for the Safe Harbor and Expert Determination methods, and the [HHS Security Rule overview](https://www.hhs.gov/hipaa/for-professionals/security/index.html) for the broader administrative, physical, and technical safeguards.

---

## Quickstart (How to run locally)

### 1. Prerequisites & Environment Setup
Clone the repository, copy `.env.example` to `.env`, and replace the placeholder API key and JWT secret. Compose supplies its own database and Redis URLs to the API container. If you already have a `.env`, add `SECRET_KEY` without replacing the existing values.
```bash
GROQ_API_KEY=gsk_your_key_here
SECRET_KEY=replace_with_a_long_random_value
DATABASE_URL=postgresql://myuser:mypassword@localhost:5432/medical_db
REDIS_URL=redis://localhost:6379/0
```

### 2. Run with Docker Compose
Boot PostgreSQL with `pgvector`, Redis, and the API:
```bash
docker compose up -d --build
```

Access the services:
- **FastAPI Swagger Docs:** `http://localhost:8000/docs`
- **Health checks:** `http://localhost:8000/health/live` and `http://localhost:8000/health/ready`

For the optional N8N editor, run `docker compose --profile workflow up -d` and open `http://localhost:5678`.

### Demo walkthrough

Use `/docs` with synthetic text such as `documents/patient_cardio.txt`:

1. Create a user with `POST /register` (password at least 12 characters), then get a bearer token with `POST /token`.
2. Use **Authorize** in Swagger, upload a file from `output/pdf/` with `POST /upload`, and poll the returned job ID at `GET /jobs/{job_id}`.
3. Search with `POST /search`, then ask `POST /chat/agent` a question about the record. The response includes `sources` with document IDs and filenames. The streaming endpoint emits the same sources in an SSE `sources` event.
4. Create a second user and repeat the search. That user cannot read the first user's search results or job status.

### 3. Run Locally with Virtual Environment
*(Ensure you have PostgreSQL and Redis running locally)*
```bash
# Create and activate a virtual environment
python -m venv .venv
.\.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Start FastAPI server
uvicorn app.main:app --reload --port 8000
```

### 4. Running the Test Suite
```bash
pytest
```
The suite covers extraction validation, privacy redaction, agent source handling, tenant boundaries in search and job status, and upload validation. It uses test doubles for PostgreSQL, Redis, embeddings, and the external LLM; a live Docker smoke test remains a separate verification step.

