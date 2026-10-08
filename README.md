# Clinical AI Extraction & Orchestration Pipeline (POC)

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
1. **Asynchronous Ingestion**: Documents are ingested, redacted, chunked, embedded, and stored in the background with Redis job state tracking.
2. **Deterministic Multi-Tenancy**: Data access, tool execution, and query lookups are strictly bound to the authenticated user on the server side.
3. **Evidence-Gated Answering**: The clinical QA agent requires explicit source grounding and withholds answers if relevant sources are absent.

---

## Features

- **Asynchronous Ingestion & Job Tracking:** Accepts UTF-8 text and PDF documents, extracts text, and processes documents in the background (`GET /jobs/{job_id}`).
- **Idempotency Support:** Supports `Idempotency-Key` headers on `/upload` to safely handle client retries.
- **Automated PII/PHI Redaction:** Integrates Microsoft Presidio for automated text sanitization prior to model provider transmission and persistence.
- **Recursive Chunking & Embeddings:** Documents are partitioned via `RecursiveCharacterTextSplitter` (500-char chunks, 50 overlap) and embedded into 384-dimensional dense vectors using HuggingFace (`sentence-transformers/all-MiniLM-L6-v2`).
- **Semantic Vector Search:** High-performance cosine similarity search powered by PostgreSQL with `pgvector`, partitioned by tenant.
- **Autonomous Clinical Agent & Tool Calling:** Dynamically calls vector search tools with server-enforced user boundaries and returns responses with document citations (`[doc:ID]`).
- **Server-Sent Events (SSE) Streaming:** `/chat/stream` streams answer tokens in real time after emitting retrieval source metadata.
- **Tenant Isolation:** Enforced JWT authentication with Bcrypt password hashing. Database queries and tool invocations strictly bind `user_id` on the backend.
- **Resilience & Fallbacks:** Employs exponential backoff retry policies (`tenacity`) for external LLM API calls with graceful structured fallbacks.

---

## Tech Stack

| Component | Technologies |
|---|---|
| **API & Core** | FastAPI, Pydantic v2, SQLAlchemy 2.0, Uvicorn |
| **AI & NLP** | Groq / OpenAI (`AsyncOpenAI`), HuggingFace (`sentence-transformers`), LangChain |
| **Storage & Vectors** | PostgreSQL 16 with `pgvector` extension |
| **Caching & Job State** | Redis |
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
| **Cross-User Job Infiltration** | Owner ID stored with each Redis job record; verified upon lookup. | `test_api_boundaries.py` |
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
