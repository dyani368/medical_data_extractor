# Clinical Document Intelligence Platform

**Clarity** is the React workspace for this platform: document uploads, extraction review, source passages, and streamed conversations.

Live workspace: [Clarity](http://32.236.61.231/). Sign in with an existing account or explore the clearly labeled demo without signing in. The IP deployment uses HTTP; use demo records only until HTTPS is configured.

Run `docker compose up -d --build` and open `http://localhost` or `http://localhost:8000`.
The frontend and API share one origin through Nginx. Existing API routes and `/docs` remain available; the frontend uses the `/api/` prefix.

For frontend development, install Node.js 22 or later and pnpm 11.25.0, then run `pnpm install --frozen-lockfile` and `pnpm dev` from `frontend/`. Vite proxies `/api/` to the local backend on port 8000.
The demo workspace contains explicitly labeled saved examples, and the downloadable PDFs contain invented records. Real uploads and conversations require an account.
Authentication tokens are held in browser session storage and cleared on sign-out; expired sessions return to the sign-in screen.

The Docker API requests embeddings from an authenticated, internal-only endpoint in the worker process. Ingestion and search share one model instance and a persistent model cache, reducing memory use on the small EC2 host. The worker port is not published. Locally, without `EMBEDDING_SERVICE_URL`, embedding inference runs in-process.

A production-style proof of concept demonstrating asynchronous document ingestion, structured clinical entity extraction, semantic vector search, and evidence-grounded agentic question answering over synthetic records.

---

## Overview & Architecture

```
                    ┌──────────────────────────────────────────────┐
                    │               FastAPI Gateway                │
                    │   JWT Authentication & User Scoping         │
                    └───────┬──────────────┬──────────────┬────────┘
                            │              │              │
           POST /upload     │ POST /search │ POST /chat   │
                            ▼              ▼              ▼
                 ┌─────────────┐    ┌─────────────┐ ┌─────────────┐
                 │ Background  │    │  pgvector   │ │ Clinical    │
                 │ Ingestion   │    │  Similarity │ │ Agent (LLM) │
                 │ Worker      │    │  Search     │ │ + Tool Call │
                 └──────┬──────┘    └──────┬──────┘ └──────┬──────┘
                        │                  │               │
                        ▼                  ▼               ▼
                 ┌─────────────┐    ┌─────────────┐ ┌─────────────┐
                 │ Presidio    │    │ Cosine Dist │ │ Grounded    │
                 │ Redaction & │    │ Filtered by │ │ Evidence    │
                 │ Chunking    │    │ user_id     │ │ Verification│
                 └──────┬──────┘    └─────────────┘ └─────────────┘
                        │
                        ▼
                 ┌─────────────┐
                 │ PostgreSQL  │
                 │ & Redis     │
                 └─────────────┘
```

The pipeline is designed around defense-in-depth security principles:
1. **Durable Asynchronous Ingestion**: The API performs bounded format/size checks, stores the source briefly in a private shared volume, and commits a PostgreSQL job. A separate Python worker parses pages, extracts tables and figures, redacts extracted text, and resumes persisted element/chunk checkpoints after a crash. API restarts do not lose queued jobs; the raw upload is deleted after partitioning.
2. **Deterministic Multi-Tenancy**: Data access, tool execution, and query lookups are strictly bound to the authenticated user on the server side.
3. **Evidence-Gated Answering**: The clinical QA agent requires explicit source grounding and withholds answers if relevant sources are absent.

---

## Features

- **Asynchronous Ingestion & Job Tracking:** Accepts UTF-8 text and PDFs up to 20 MB/100 pages; the worker parses the document off the API process and reports progress through `GET /jobs/{job_id}`.
- **Idempotency Support:** Supports `Idempotency-Key` headers on `/upload` to safely handle client retries.
- **Automated PII/PHI Redaction:** Integrates Microsoft Presidio for automated text sanitization prior to model provider transmission and persistence.
- **Recursive Chunking & Embeddings:** Documents are partitioned via `RecursiveCharacterTextSplitter` (500-char chunks, 50 overlap) and embedded into 384-dimensional dense vectors using HuggingFace (`sentence-transformers/all-MiniLM-L6-v2`).
- **Hybrid Search:** Tenant-scoped `pgvector` and PostgreSQL full-text rankings fused for candidate passage retrieval.
- **Autonomous Clinical Agent & Tool Calling:** Dynamically calls vector search tools with server-enforced user boundaries and returns responses with document citations (`[doc:ID]`).
- **Bounded multi-step tool use:** The agent can search, inspect neighboring chunks, and retrieve extraction results across up to three tool rounds; server-side user scoping applies to every lookup.
- **Server-Sent Events (SSE) Streaming:** `/chat/stream` streams answer tokens in real time, then emits cited source metadata.
- **Focused agent tools:** Search passages, retrieve a saved extraction, and load neighboring chunks from a retrieved document; every lookup uses the authenticated user scope.
- **Document and conversation API:** List, inspect, and delete the authenticated user's uploaded documents; retrieve per-chunk extraction outcomes and list or reopen conversation history.
- **Page-aware provenance:** PDF chunks retain their source upload, chunk order, and page number so citations and related-chunk retrieval can point back to the source location.
- **Mixed-content PDF processing:** PyMuPDF extracts ordered text, structured table passages, and bounded image/figure elements with page, section, and nearby-text context. Images are stored in a private Docker volume, described for semantic retrieval, and attached to the final vision-model answer when retrieved; citations can display the original figure. Up to 30 visuals per PDF are indexed.
- **Large-file API responsiveness:** The API queues the original upload quickly; PDF parsing, redaction, image description, embedding, and extraction happen in the separate recoverable worker. Page count, file size, image count, and image bytes are bounded.
- **Extraction outcome reporting:** Jobs distinguish successful ingestion with extraction errors, and extraction records expose per-chunk success/failure state and error type rather than hiding fallback results.
- **Queue recovery:** One ingestion job per worker process; three attempts maximum with bounded backoff. Leases prevent concurrent ownership and fence stale workers before chunk commits. Extraction/provider failures remain explicitly visible as `completed_with_errors`.
- **Retention:** Durable terminal job records expire after 30 days; idempotency keys after 24 hours. Raw PDF uploads are removed after partitioning (and stale orphan uploads are swept); extracted text is redacted before persistence/model calls. Image pixels are retained privately for source inspection and vision answering until the authenticated document is deleted. Only use synthetic or de-identified records: visual pixels are sent to the configured external LLM provider and are not OCR-redacted in this demo. Conversation history persists. Redis-only historical status remains readable until its TTL expires.
- **Schema migrations:** Alembic applies versioned schema migrations at API startup. Existing deployments are baselined against their existing tables; future schema changes belong in a new migration revision.
- To apply versioned schema changes manually, install `requirements.txt` and run `alembic upgrade head` from the project root. The first revision records the current schema without dropping existing tables or data.
- **Tenant Isolation:** Enforced JWT authentication with Bcrypt password hashing. Database queries and tool invocations strictly bind `user_id` on the backend.
- **Resilience & Fallbacks:** Employs exponential backoff retry policies (`tenacity`) for external LLM API calls with graceful structured fallbacks.

---

## Tech Stack

| Component | Technologies |
|---|---|
| **API & Core** | FastAPI, Pydantic v2, SQLAlchemy 2.0, Uvicorn |
| **AI & NLP** | Groq / OpenAI (`AsyncOpenAI`), HuggingFace (`sentence-transformers`), LangChain |
| **Storage & Vectors** | PostgreSQL 16 with `pgvector` extension |
| **Queue & Job State** | PostgreSQL leases/checkpoints; Redis for legacy state and worker health |
| **Frontend** | React, TypeScript, Vite, Nginx |
| **Security & Privacy** | PyJWT, Passlib (Bcrypt), Microsoft Presidio |
| **Resilience & Fault Tolerance** | Tenacity |
| **Infrastructure & CI/CD** | Docker, Docker Compose, GitHub Actions |
| **Testing** | Pytest, Pytest-Asyncio |

---

## Core API Endpoints

| Method | Endpoint | Description | Auth Required |
|---|---|---|:---:|
| `POST` | `/register` | Register a new user | No |
| `POST` | `/token` | Authenticate and obtain JWT access token | No |
| `GET` | `/me` | Get profile of currently authenticated user | Yes |
| `POST` | `/upload` | Queue document for async ingestion | Yes |
| `GET` | `/jobs/{job_id}` | Poll ingestion status | Yes |
| `GET` | `/documents` | List the authenticated user's uploaded documents | Yes |
| `GET` | `/documents/{document_id}` | Retrieve a document and its ordered source chunks | Yes |
| `GET` | `/documents/{document_id}/extraction` | Retrieve per-chunk extraction outcomes | Yes |
| `GET` | `/chunks/{chunk_id}` | Open an owned passage cited by an answer | Yes |
| `DELETE` | `/documents/{document_id}` | Delete an uploaded document and its extraction results | Yes |
| `GET` | `/conversations` | List the authenticated user's conversations | Yes |
| `GET` | `/conversations/{conversation_id}` | Retrieve a conversation's user and assistant messages | Yes |
| `POST` | `/search` | Semantic vector search across user records | Yes |
| `POST` | `/chat/agent` | Autonomous clinical QA agent with tool execution | Yes |
| `POST` | `/chat/stream` | Stream QA answers and sources via Server-Sent Events | Yes |
| `GET` | `/health/live` | Process liveness probe | No |
| `GET` | `/health/ready` | Database & Redis readiness probe | No |

---

## Security Architecture & Scope

This repository is an engineering demonstration evaluated on synthetic datasets. It illustrates production-grade application security principles for clinical AI pipelines:

### Threat Model & Mitigation Matrix

| Potential Risk | Implemented Control | Test Verification |
|---|---|---|
| **Cross-Tenant Vector Query Injection** | LLM cannot supply tenant IDs; backend forcibly binds `user_id`, DB session, and query limits. | `test_agent_service.py`, `test_doc_search.py` |
| **Cross-User Job Infiltration** | Owner-scoped durable job lookup, with owner checks on historical Redis jobs. | `test_api_boundaries.py`, `test_ingestion_queue.py` |
| **Sensitive Entity Leakage to Providers** | Input sanitized via Presidio before LLM call; chunks sanitized before response assembly. | `test_privacy.py`, `test_extraction_privacy.py` |
| **Hallucinated Clinical Statements** | Agent refuses to generate unsupported answers when retrieval returns no sources. | `test_agent_service.py` |

### Production Readiness Considerations
For deployment in regulated healthcare environments (HIPAA / GDPR / 21 CFR Part 11), the following controls are recommended:
- Migration from in-process background tasks to a distributed, persistent message broker (e.g., Celery / RabbitMQ / SQS).
- Implementation of PostgreSQL Row-Level Security (RLS) policies at the database layer.
- An encrypted token vault for reversible pseudonymization alongside expert de-identification determination.
- Immutable, tamper-evident audit logs with centralized security information and event management (SIEM).

---

## Quickstart Guide

### 1. Environment Configuration

Clone the repository and create your `.env` configuration file:

```bash
git clone https://github.com/dyani368/medical_data_extractor.git
cd medical_data_extractor
cp .env.example .env
```

Configure your environment variables in `.env`:
```env
GROQ_API_KEY=gsk_your_key_here
SECRET_KEY=generate_a_secure_random_hex_string
DATABASE_URL=postgresql://myuser:mypassword@localhost:5432/medical_db
REDIS_URL=redis://localhost:6379/0
```

### 2. Deploy with Docker Compose

Start the full stack (FastAPI, PostgreSQL with `pgvector`, and Redis):

```bash
docker compose up -d --build
```

Verify service availability:
- **Interactive API Documentation:** `http://localhost:8000/docs`
- **Liveness Check:** `http://localhost:8000/health/live`
- **Readiness Check:** `http://localhost:8000/health/ready`

*(Optional)* Launch with N8N workflow engine:
```bash
docker compose --profile workflow up -d
```

---

## Verification & Walkthrough

1. **Authentication:**
   - Create a user via `POST /register`.
   - Obtain a bearer token via `POST /token`.
   - Click **Authorize** in the Swagger UI and enter your token.

2. **Ingestion:**
   - Submit a test document via `POST /upload` (e.g. `documents/patient_cardio.txt`).
   - Monitor the ingestion job with `GET /jobs/{job_id}` until status is `completed`.

3. **Search & QA:**
   - Perform a semantic search on clinical terms using `POST /search`.
   - Query the clinical agent via `POST /chat/agent` or stream answers via `POST /chat/stream`.

4. **Multi-Tenancy Verification:**
   - Register a second user account.
   - Run a query against the documents uploaded by the first user; verify that no cross-tenant data is leaked.

---

## Running Tests

Execute the automated test suite:

```bash
pytest -v
```

The test suite validates:
- Pydantic schema constraints and entity extraction logic
- Privacy filters and text sanitization pipelines
- User-scoped multi-tenancy boundaries on search and job status
- Tool execution context isolation
